# Download batch-size comparison — Poor Connectivity (batch=1) vs Normal (batch=10) on fast LAN (2026-06-19)

**Goal:** measure, not assume, whether larger batches are actually faster on the
current high-speed local network — comparing Poor Connectivity mode (1 image/batch)
against Normal mode (adaptive batch, default 10).

## TL;DR
- **On this LAN, Normal (batch=10) is ~1.5–1.6× faster than batch=1** for full-series
  transfer — the assumption "bigger batch = faster" *holds here*. The gain comes from
  **per-request server overhead** (≈40 ms each), not network latency, so it's real even
  on a 0.5 ms-RTT LAN.
- **First-image latency is a TIE (~0.05 s)** in both modes, because the first-image
  prime already fetches slice 1 as a single image in Normal mode too.
- **🔴 CRITICAL (correctness, found during the test):** Normal batch>1 mode
  **silently dropped the last 12 of 52 images** on one series (got instances 1–40,
  missed 41–52), reproducibly, and the viewer still showed "52/52". **Poor mode
  (batch=1) downloaded all 52/52.** This is a data-completeness bug in the batch>1
  path and outweighs the speed result — see §5.

## 1. Test environment
| | |
|---|---|
| Build | source / dev (`.venv` python, branch `beta-version`), FAST viewer (`pydicom_qt`) |
| Server | **razi** `192.168.2.222` (socket port 50052), same fast LAN, stable, not throttled |
| Date | 2026-06-19, ~14:35 and ~16:42–16:50 |
| Mode switch | `config/servers.json` `poor_connectivity` flipped live (no restart — resolver re-reads per download) |
| Measurement | per-image / per-series timing from `user_data/logs/download_diagnostics.log` |

**Important method note:** a standalone download harness was not possible — the socket
auth token is held in-memory in the running app only, so all downloads were driven
through the authenticated app (computer-use), and timing read from logs.

## 2. Studies used (CT, yesterday 2026-06-18, from razi)
| Patient | ID | Study | Series measured | Img/series | ~MB/img |
|---|---|---|---|---|---|
| ZAKARI RAHELA | 47233 | …86508 | 201 / 202 / 203 | 40 / 240 / 120 | ~0.70 |
| TAJIK MARYAM | 47221 | …86507 | 201 / 202 | 52 / 52 | ~1.9 / ~1.25 |

The **controlled A/B** is on **47221** — the *same series* were downloaded at batch=1
and batch=10, each from an empty folder (cache moved aside between runs), so batch size
is the only variable. 47233 provides additional batch=1 points. (Cross-study μB/s is
not comparable because per-image size differs — hence the same-series design.)

## 3. Transport timing — controlled same-series (47221, identical images)
| Series (52 img) | Poor / batch=1 | Normal / batch=10 | Result |
|---|---|---|---|
| **201** | 52 imgs, **5.8 s** (9.0 img/s) | 52 imgs, **3.7 s** (14.1 img/s) | **batch=10 1.57× faster, both complete** |
| **202** | 52 imgs, **4.2 s** (12.4 img/s) | **40 imgs**, 2.1 s — **incomplete** | speed n/a (dropped 12 imgs; see §5) |

Additional batch=1 points (47233, 0.70 MB images): 40 img/3.2 s (12.5 img/s),
120 img/9.5 s (12.6), 240 img/20.3 s (11.8) — i.e. batch=1 sustains ~12 img/s steadily.

**Why batch=10 is faster (and it's not the network):** batch=1 issues one
`GetSeriesImages` request per image (52 requests); batch=10 issues ~6. Each request
carries a fixed server-side cost (query + seek + encode setup) of roughly 40 ms. The
~2 s gap (5.8 → 3.7 s) ≈ (52−6) requests × ~40 ms. Network RTT on the LAN is negligible;
the saving is per-request server work.

## 4. First-image latency & perception
| Metric | Poor / batch=1 | Normal / batch=10 |
|---|---|---|
| First image arrives | **~0.05 s** | **~0.05 s** (first-image prime fetches slice 1 singly) |
| Thumbnails appear | fast, progressive | fast, progressive |
| Full small study (≈94 img) | a few seconds | a few seconds |
| Viewport first paint | instant once a series is dragged in (FAST render ~67 ms, local) | same |

So **for the user-perceived "time to first image", the two modes are equivalent** — the
prime already gives Normal mode the single-image fast start. Poor mode's only perception
cost is that the *full stack* finishes ~1.5× later.

## 5. 🔴 Data-completeness finding (normal batch>1 dropped images)
On series **202** (52 images), repeated cleanly:
- batch=1 (poor): **52/52** on disk, log `52 downloaded, 0 skipped`.
- batch=10 (normal): **40/52** on disk, log `40 downloaded, 31 skipped` — **on two
  independent runs**, including the very first (unconfounded) normal-mode open.
- The missing files are the **contiguous tail, instances 41–52**; the 31 "skipped" were
  duplicate re-fetches of earlier instances.
- **The viewer displayed "52/52"** (count from server-expected) while disk held 40 — a
  silent **false-complete**.
- Same study's series **201** (also 52 img) *did* complete at batch=10 (with 11 duplicate
  skips), so this is **series-specific and intermittent**, not "every series".

**Likely cause (to confirm):** batch>1 pagination/offset misalignment — the first-image
prime advances `batch_start` to 1 (not a multiple of the restored batch size), and the
server's batch_index mapping then overlaps early batches (the duplicates) and terminates
`has_more` before the tail. Prime + pagination interaction is the prime suspect.

**This is more important than the speed result.** Poor mode (batch=1) requests every
index individually and was complete; the batch>1 path was not. The clinical data on disk
was restored to the complete (batch=1) copy after the test.

## 6. Conclusions (answers to the test questions)
1. **Is larger batch actually faster on this LAN?** Yes — ~1.5–1.6× faster full-series
   transfer (batch=10 vs 1), from per-request server overhead, not network latency.
2. **Is batch=1 meaningfully slower?** Moderately — ~1.5× slower to finish a full series
   (e.g. 5.8 s vs 3.7 s for 52 imgs). Steady ~12 img/s; fine for small/medium series,
   noticeable on large stacks.
3. **Better first-image latency?** Tie (~0.05 s) — the prime equalizes it.
4. **Better full-download time?** Normal (batch=10) — *when it completes correctly*.
5. **Which feels smoother?** Equivalent to first image; Normal finishes the whole stack
   sooner.
6. **Reconsider default batch size?** No — 10 is a good speed default. But the batch>1
   **tail-drop bug must be fixed** before Normal mode can be trusted for completeness.
7. **Adaptive batch sizing?** Already present (Poor-mode manual switch + adaptive growth).
   The completeness bug argues for caution, not more aggressive batching.

## 7. Recommendations (evidence-based)
- **Keep Normal default batch = 10** for speed (≈1.5× faster, real).
- **Keep Poor mode = batch=1** — it is both the resilient-link mode *and*, on this data,
  the **complete** mode. On razi today it is the safer choice until §5 is fixed.
- **🔴 P0 follow-up:** root-cause the batch>1 tail-drop (s202: got 1–40, missed 41–52,
  31 duplicates). Capture per-batch request/offset logs; test with the first-image prime
  disabled (`AIPACS_FIRST_IMAGE_PRIME=0`) to confirm the prime↔pagination interaction;
  add a **post-download completeness assertion** (on-disk count vs server-expected) so a
  short series can never silently show "52/52" with 40 files.
- **First-image-priority is already done** (the prime) and works — no separate change
  needed for first-image latency.

## 8. Limitations
- Same-series A/B is one study (47221), two series; the completeness bug reproduced on one
  series (202) but not the other (201) — needs broader sampling.
- batch=5 not separately tested (Normal default is 10 + growth).
- "Time to first image in the viewport" was inferred from the prime behavior + logs; the
  viewport auto-loads only after a series is dragged in (FAST viewer), which was not part
  of each timed open.
- Network was genuinely fast/stable; Poor mode's *resilience* advantage (its actual
  purpose) is not exercised here — see the 2026-06-19 poor-connectivity verification.

## 9. Fix applied (2026-06-19) — `modules/download_manager/network/socket_client.py`
Root cause confirmed by code: the server pages by `batch_index = batch_start //
batch_size` (`download_batch`). `batch_start` advances **additively** but adaptive
mid-series **growth** multiplies `batch_size`, so `batch_start` stops being a multiple
of the new size and the reconstructed `batch_index` repeats / sticks near 0 — the
client re-fetches the head (the duplicates) and never requests the tail. (Growth logs
at INFO, filtered from `download_diagnostics.log`, which is why "0 grew events" appeared
despite growth firing.)

Three changes, all flag-gated default-on, legacy preserved:
1. **`_PAGINATION_SAFE`** (`AIPACS_DOWNLOAD_PAGINATION_SAFE`, default 1) **disables
   mid-series batch growth**, so `batch_size` is constant and `batch_index =
   batch_start // batch_size` tiles the series exactly. The first-image prime
   (size 1 → full) and the byte-cap halve are alignment-safe and unchanged.
2. **Completeness guard** after each series: compares on-disk unique count vs the
   server's `expected_count`; if short, **fills the gap** with correctly-tiled
   constant-size batch requests (reusing the atomic-write + file-dedup) and logs
   `[SERIES_COMPLETE]` or `[INCOMPLETE_SERIES]`. A series can no longer silently
   report "N/N" with fewer files.
3. **`[BATCH_TRACE]`** WARNING per batch (`AIPACS_DOWNLOAD_BATCH_TRACE`, default 1) —
   one line with `batch_index / size / received / has_more`, so a stuck/repeating
   index is visible in `download_diagnostics.log`.

Verified: `tests/code/download_manager` = **233 passed** (`.venv`); plugin mirror
parity 389/389; `socket_client.py` compiles. Speed impact of disabling growth is
small (the measured ~1.5× came at constant batch≈10; growth only ramped toward 40).

### Verification plan for the both-mode re-run (what I will check in the logs)
**Restart the app first** so the new `socket_client.py` is loaded, then open an
uncached CT study in each mode. I will grep `user_data/logs/download_diagnostics.log`:
- **Every series** ends with `[SERIES_COMPLETE] on_disk=N expected=N` and **no**
  `[INCOMPLETE_SERIES]` (or, if one appears, it must be followed by a gap-fill
  `[SERIES_COMPLETE] (gap-fill resolved)`).
- **Normal mode** `[BATCH_TRACE]` shows `batch_index` **advancing** 0,1,2,… at a
  **constant** `size` (no growth) — not stuck at 0.
- **Poor mode** `[BATCH_TRACE]` shows `size=1` throughout, index advancing per image.
- On-disk file count per series == server expected (spot-check), confirming no tail drop.
