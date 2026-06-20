# Investigation — download modes, incomplete series, and white thumbnails (2026-06-19)

Evidence-based answers to the three requested investigations. All conclusions are
from logs (`user_data/logs/download_diagnostics.log`, `viewer_diagnostics.log`), the
clinical DB (`user_data/database/dicom.db`, read-only), the thumbnail PNGs on disk,
and the source code — not assumptions.

---

## 1. Download-mode comparison — Poor (batch=1) vs Normal (batch≈10)

Measured on the current fast LAN (Razi). The cleanest number is the **same-series**
A/B on patient 47221 (identical CT series downloaded at each batch size, empty start).

| KPI | Poor (batch=1) | Normal (batch≈10) | Winner |
|---|---|---|---|
| Time to **first image** (on drag) | ~0.05 s | ~0.05 s | **Tie** — the first-image *prime* fetches slice 1 as one image in both modes |
| Time to **first thumbnail** | ~0.2 s | ~0.2 s | **Tie** — thumbnails are a separate server call (`right_panel_socket_done thumbnail_count=8` @ ~224 ms from open), independent of download batch mode |
| Time to **patient open** (tab + thumbnails shown) | ~0.22 s | ~0.22 s | **Tie** |
| Time to **50th image** | ~3.9 s | ~3.4 s | Normal |
| Time to **last image** (52-img series 201) | **5.8 s** | **3.7 s** | **Normal (~1.6× faster)** |
| Time to **full series** (per-image rate) | ~9–12 img/s | ~14 img/s | **Normal** |
| Time to **full study** | proportional | ~1.5× faster | **Normal** |
| **Retry count** | 0 | 0 | Tie |
| **Failed requests** | 0 | 0 | Tie |
| **UI smoothness** | steady (small batches) | one ~1 s `[MAIN_THREAD_STALL]` under burst | Poor slightly smoother under burst |
| **DM stability** | stable | stable | Tie (0 `[INCOMPLETE_SERIES]` after the fix below) |
| **Perceived responsiveness** | first image instant | first image instant | Tie to first image; Normal finishes the whole stack sooner |

**Why Normal wins on throughput (measured, not assumed):** batch=1 issues one
`GetSeriesImages` request per image (52 requests); batch≈10 issues ~6. Each request
carries a fixed **server-side overhead (~40 ms)**, so the ~2 s gap (5.8 → 3.7 s) is
saved request overhead, **not** network bandwidth (LAN RTT is ~0.5 ms).

**Verdict:** On a fast/stable LAN, **Normal (larger batch) is the better mode** —
~1.5–1.6× faster to complete a series/study, with identical first-image and
first-thumbnail latency and equal stability. Poor mode is **not** about speed here;
its value is resilience on a genuinely unstable link (image-level retry, keep what's
on disk). Detail: `docs/reports/BATCH_SIZE_COMPARISON_POOR_VS_NORMAL_2026-06-19.md`.

---

## 2. Incomplete series — duplicate / overlapping identity?

**Yes — incomplete series are caused by a `series_number` collision, NOT by wrong
SeriesInstanceUID handling.** Evidence from the DB for study …86503:

| series_pk | series_number | SeriesInstanceUID (tail) | image_count | instances on disk |
|---|---|---|---|---|
| 9874 | **203** | …80753363530000 | 24 | **0** (lost) |
| 9875 | **203** | …1781767938298 | 156 | 132 |

- **One real SeriesInstanceUID is NOT split into two.** The opposite: **two distinct
  SeriesInstanceUIDs legitimately share `series_number` 203** (a 24-image derived
  series + the 156-image CT). The DB stores them as **two separate rows** with
  distinct `series_pk` and `series_uid` — `DUPLICATE series_uid rows: none`. So the
  database **models identity correctly**: `study_pk` → `series_pk`(+`series_uid`) →
  instances(`sop_uid`, `series_fk`). StudyUID + SeriesUID + SOPUID are used correctly.
- **The bug is the on-disk FOLDER, which is keyed by `series_number`, not
  SeriesInstanceUID.** Both series 203 resolved to `…/86503/203/`, so the second
  download overwrote the first → series_pk 9874 ends with **0 instances** ("the series
  that isn't connected"). This is the only overlap — a disk/folder identity collapse,
  not a DB/cache record duplication and not instances attached to the wrong series.
- **Download manager does NOT split or merge series.** It downloads per
  SeriesInstanceUID; the collapse happens only at the folder-name step.
- **Thumbnail vs viewer source mismatch:** see §3 — yes, the thumbnail comes from a
  different source (server PNG) than viewer loading (local DICOM), which is why a
  series can render correctly in the viewer yet show a wrong thumbnail.

**Status:** fixed (committed `d6768f86`) — `core/series_folder.py`
`resolve_series_folder_name()` gives colliding series distinct folders (largest keeps
the bare number so the display is unchanged; others preserved as
`<number>__<sha1(uid)[:8]>`). Plus the batch-pagination tail-drop fix (`47dd51ae`) and
the per-series completeness guard, which now logs `[SERIES_COMPLETE]/[INCOMPLETE_SERIES]`.

---

## 3. & 4. Thumbnail source, and why some are white

**Thumbnails are RECEIVED FROM THE SERVER — not generated locally.** Evidence:
- `GetStudyThumbnails` returns base64 PNG bytes per series; the client decodes
  (`grpc_client.py` base64) and writes them **as-is** to
  `THUMBNAIL_PATH/<study_uid>/<series_number>.png` (`executor.py::_save_thumbnails`)
  and an in-memory `ThumbnailStore`. The open trace confirms the server supplied all
  of them: `right_panel_display_input … thumbnail_count=8 with_inline_data=8`.
- There is **no local DICOM→thumbnail generation** in the client, and **no
  window/level, rescale, or VOI-LUT is applied** to thumbnails anywhere. The DB does
  not hold them either (`main_thumbnail` empty, `thumbnail_path` NULL).

**Why some appear completely white — root cause = the server's thumbnail render, not
the client.** Hard evidence:
- The white thumbnails are **byte-identical across different series and studies**:
  md5 `55A978A3…` (668 B) is the *same file* for 86503/201, 86503/203, 86505/201,
  86505/203, and `03343CC3…` for both 101s. Real per-series renders cannot be
  byte-identical — this is a single saturated-white image.
- It correlates exactly with the **lung window**: the white series are the ones whose
  DICOM `WindowCenter/WindowWidth = -600/1200` (series 201, 203). Soft-tissue series
  (`50/350`: series 202, 122655019) get **real, distinct** thumbnails.
- That white PNG matches **no bundled client asset** and there is **no client
  placeholder code** — and the server returned data for all 8 series. So the server
  itself produced a saturated-white image for the negative-center lung window
  (it does not apply the lung window correctly), and produced the *identical* white
  output for both lung series.
- **Pipeline mismatch confirmed:** the FAST viewer renders those very series
  **correctly** (`viewer_diagnostics.log: FAST:first_image_visible series=203 …
  filter_status=applied`) because it applies the DICOM WC/WW from the local DICOM —
  while the thumbnail is the server's mis-windowed PNG. Same series, two pipelines,
  two results.

So, mapping to the checklist: it is **not** a client WC/WW / VOI-LUT / rescale /
normalization bug (the client doesn't process thumbnails at all), **not** a
non-representative-slice or pre-index-timing bug, and **not** a local algorithm. It is
a **server thumbnail generated with the wrong window** (saturated white for
negative-center CT), displayed by the client as-is — i.e. "using a server thumbnail
that was generated incorrectly" + "mismatch between thumbnail pipeline and viewer
rendering pipeline."

---

## 5. What code path should be fixed

- **Incomplete series (done):** `modules/download_manager/download/series_downloader.py`
  + `modules/download_manager/core/series_folder.py` (folder disambiguation);
  `network/socket_client.py` (batch tiling + completeness guard).
- **White thumbnails (recommended, not yet implemented):** stop depending on the
  server's thumbnail for CT. Add a **client-side thumbnail generator** that, after a
  series downloads, renders a thumbnail from the middle local DICOM slice **through
  the viewer's own window-level pipeline** (`modules/viewer/fast/lightweight_2d_pipeline.py`
  `_window_level_to_uint8_with_voi_function`, using the DB's per-series WC/WW which is
  already stored — e.g. 201 = -600/1200). Wire it into the thumbnail write
  (`executor.py::_save_thumbnails`) / `ThumbnailImageSourceService` as the source of
  truth, or at least as a fallback when the server thumbnail is blank/saturated
  (detectable: near-uniform ≥240). This makes the thumbnail and the viewport use the
  **same** rendering, which is the correct fix. (The server's thumbnail renderer
  should also be corrected, but that is outside this codebase.)

---

## 6. Validation performed
- DB (read-only): confirmed two distinct `series_uid` rows for `series_number` 203,
  series_pk 9874 with **0 instances** (the lost series); identity model correct.
- Thumbnail PNGs on disk: pixel stats (white% / mean) + **md5 hashing** proving the
  white images are a single byte-identical saturated-white file shared across series.
- Logs: `with_inline_data=8` (server supplied all thumbnails); `FAST:first_image_visible
  … filter_status=applied` (viewer renders the same series correctly); batch KPIs +
  `[SERIES_COMPLETE]/[INCOMPLETE_SERIES]/[BATCH_TRACE]` from the both-mode rerun.
- Tests: `tests/code/download_manager` **245 green** (.venv), incl. the new collision
  + pagination guards; plugin mirror parity **390/390**.

## 7. Is the fix in the final build path?
- **Series-collision + batch-pagination + completeness fixes: YES.** They are in
  `modules/download_manager/...` which is plugin-mirrored (verified 390/390) and
  committed (`47dd51ae`, `d6768f86`), so they ship in the installer build. (Other
  clinic PCs need a rebuilt installer to receive them.)
- **White-thumbnail (local generation): NOT YET** — this report recommends it; it is
  not implemented. When built it would live in `modules/viewer` + `modules/download_manager`
  (the latter mirrored) and ship the same way.
