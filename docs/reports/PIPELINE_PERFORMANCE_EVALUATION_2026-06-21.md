# Pipeline performance evaluation — is every stage optimized? where are the bottlenecks?

**Date:** 2026-06-21
**Branch/commit:** `beta-version` @ `56ca5eec`
**Scope:** the same pipeline — not-downloaded study double-click → thumbnail load → drag → import → decode → display → cache.
**Method:** code cost analysis (file:line) + per-stage timing mined from today's `user_data/logs/` + two micro-benchmarks run in the real `.venv`. READ-ONLY — **no code was changed.**

## Direct answer

**No — not every stage is fully optimized, but most are.** The **viewer half (stages 6–9: import → decode → display → cache) is well-optimized and at/near its KPI targets.** The remaining bottlenecks are concentrated in three places, all latency/throughput (not clinical-correctness):

1. **Download round-trips for a not-downloaded series** — the dominant wall-clock cost (~5 s for a 160-image series on a *fast* LAN), made worse by a **systematic prime/pagination off-by-one** that forces an extra gap-fill on every series whose image count ≡ 1 (mod 10).
2. **Home-panel thumbnail load** — main-thread base64/PNG decode per card + an unbounded slow-server tail (up to the 30 s socket timeout) + a 4-call fallback chain.
3. **Multi-study series import re-scans DICOM headers off disk every load** (the DB-first metadata fast-path is disabled for multi-study), and **download DB-write spikes** contend with viewer DB reads during concurrent download+view.

Everything else (open threading, sidebar thumbnails, the multi-study index rebuild, drag/drop dispatch, decode caching/surrogates, render, the LRU/disk caches) is genuinely optimized. Details and measured evidence below.

---

## 1. Measured evidence base

### 1a. Stage-timing mined from today's logs (`stage-timing duration_ms`, current rotations)

| stage | n | avg ms | max ms | read |
|-------|---|--------|--------|------|
| `transaction_scope` | 8504 | 17.1 | **18637** | DB txn; avg fine, but worst-case 18.6 s spike (write contention) |
| `save_series_instances_total` | 4500 | 179 | 6892 | download→DB write |
| `batch_insert_instances_total` | 4551 | 178 | 6892 | download→DB write |
| `load_single_series_total` | 458 | **248** | **2462** | **the viewer import stage** — avg 248 ms, worst 2.46 s |
| `create_connection` | 2067 | 10.7 | 2321 | DB connect; 2.3 s worst = pool lock wait |
| `request_total` | 168 | 152 | 621 | socket request |
| `viewer_switch_apply` | 67 | 65 | 377 | drop→view switch apply |
| `response_header_recv` | 177 | 89 | 314 | socket header recv |
| `cache_lookup` | 811 | **1.0** | 6.3 | cache probe — fast |
| `progressive_grow_apply` | 11 | 1.3 | 6.2 | progressive grow — fast |
| `request_serialize` / `request_lock_wait` | 169 | ~0 | ~0 | negligible |

### 1b. Micro-benchmark — cold decode + window/level (real series, `.venv`, pydicom + numpy)

Series: 564-slice CT, 512×512 `uint16` (~0.52 MB/slice), 40 slices timed.

- **Cold decode (`dcmread`+`pixel_array`): avg 15.3 ms, median 11.4, min 8.7, max 55.3 ms/slice.**
- **Window/level (numpy → uint8): avg 1.71 ms/slice.**
- **Full-series serial decode estimate: ~8.6 s** (564 × 15 ms).
- *(Ran under light CPU contention; absolute numbers are realistic upper-bounds; the ranking/order of magnitude is the signal.)*

This is why the decode caching/prefetch matters: cold per-slice decode is **~3× the <5 ms warm KPI**, so an uncached series is only fast because of the LRU + background prefetch + surrogate-during-drag machinery (which the logs confirm works: 1353 `cache=hit`, 0 `cache=decode` during scrub).

### 1c. Download latency budget (from `download_diagnostics.log`, fast Razi LAN ~90 MB/s)

| step | measured |
|------|----------|
| GetStudyInfo probe | 40–536 ms (single attempt; only 2 timeouts in 7 days — the ~6 s stall guard holds) |
| priority handoff (drag→worker) | median **0 ms**, p90 0 ms, max 203 ms, 0 exhausts |
| **time-to-first-image (prime, 1 RTT)** | **~170–300 ms** (prime fired 136×) |
| per-batch round-trip (size 10) | **~140–300 ms/batch** |
| **time-to-full-series** | median **0.61 s**, p90 **2.89 s**, mean 2.33 s, max **181 s** |
| wire throughput | median **90 MB/s**, p90 107, max 407 — **wire is not the bottleneck on LAN** |

---

## 2. Per-stage optimization scorecard

Verdict key: ✅ OPTIMIZED · ⚠️ GAP · 🔴 BOTTLENECK.

| Stage | Verdict | Evidence (file:line + measured) |
|-------|---------|-------------------------------|
| **1. Open (not-downloaded)** | ✅ | All heavy I/O off the GUI thread via `asyncio.to_thread` (`_hp_patient_open.py:1120/1130/1148`); per-modality enumeration gated to multi-modality rows; GetStudyInfo single-probe (40–536 ms). No GUI-thread blocking on open. |
| **2a. Thumbnails — home right panel** | 🔴 | Main-thread `base64.b64decode`+`loadFromData`/`QPixmap(path)` **per card** in `display_thumbnails` (`right_panel_widget.py:652-695`); up-to-**4 sequential** server fallbacks (`_hp_search.py:1647-1674`); slow-server tail bounded only by the **30 s** socket timeout (`:1641`). Typical socket fetch 60–280 ms but real 2.2 s outliers + unpaired `socket_start`. |
| **2b. Thumbnails — viewer sidebar** | ✅ | Disk-cache-first reuse of the home-warmed cache (101 `ThumbnailCacheHit` vs 41 miss); off-thread fetch; render marshalled via `QueuedConnection`. No redundant primary-study refetch. (`_pw_thumbnails.py:245-343`) |
| **3. Multi-study index rebuild** | ✅ | O(series), one dict-copy + Path build per series, gated to multi-study (`len>1`), `SOURCE_PATH` imported once/call, stable slot order cached. Negligible vs network. (`_pw_thumbnails.py:462-562`) |
| **4–5. Drag + drop + coalescing** | ✅ | View switch dispatched **immediately** (`QTimer.singleShot(0)` → `change_series_on_viewer`); only the DM download-intent is debounced 350 ms (`_vc_load.py:1812`); protected-drag latch avoids COM re-entrancy. `viewer_switch_apply` avg 65 ms. |
| **6. Import / resolution** | ⚠️ | Exact-series resolution is cheap (0–3 `exists()` + entry-authority). BUT the **DB-first metadata fast-path is disabled for multi-study** (`_vc_load.py:343-345`), so a multi-study series **re-reads DICOM headers off disk every load** (`_build_metadata_headers_only`), even though the downloader already wrote that geometry to `dicom.db`. Plus a wasted `.glob("*.dcm")` count (`:704-710`). `load_single_series_total` avg 248 ms / max 2.46 s. |
| **7. Decode** | ✅ (cold cost noted) | Surrogate-during-drag eliminates foreground decode (logs: 0 `cache=decode` during scrub); L1 pixel LRU(192) + L2 disk(2 GB) cache; int16 LUT W/L; background decode GIL-isolated in a subprocess + 4-thread prefetch. Cold decode is **11–15 ms/slice** (benchmark) — so the caches/prefetch are *load-bearing*, and a cold miss while scrubbing faster than prefetch still costs ~1 frame each. |
| **8. Display / render** | ✅ | LUT W/L fast path; grayscale `Format_Grayscale8` with **no RGB copy** (RGB only for color/overlay); render-coalescing anti-flicker; no `processEvents` in the hot loop. Measured `first_image_visible` 5–30 ms vs <80 ms KPI; W/L 1.7 ms/slice. |
| **9. Cache** | ✅ | Bounded LRU (192/192, adaptive by slice count), async fire-and-forget disk writes (deferred during protected drag), collision-safe offset-key frame keys, remap/prune short-circuit when unchanged. `cache_lookup` avg 1.0 ms. RSS ~1 GB bounded. |

---

## 3. Ranked bottlenecks (consolidated, with measured impact)

**B1 — Download round-trip floor: growth disabled → fixed batch size 10. 🔴 (dominant wall-clock cost for not-downloaded).**
`_PAGINATION_SAFE` (default on, `socket_client.py:178`) disables adaptive batch GROWTH (0 growth events in the log). Every batch pays ~140–300 ms; a 160-image series = 17 round-trips ≈ **5.0 s** (logged), vs ~1.5 s if growth to size 40 were allowed. The wire is idle (90 MB/s LAN); the cost is **per-request server+framing overhead × round-trip count**. This is a *deliberate* trade for the 47221 tail-drop correctness bug, but it is the #1 latency item for a fresh series.

**B2 — Prime/pagination off-by-one → guaranteed extra gap-fill on every `expected % 10 == 1` series. ⚠️ (pure overhead, systematic).**
After the size-1 first-image prime, `batch_start` advances by the old size 1 (`socket_client.py:1721`), so `batch_index = 1//10 = 0` and the next size-10 batch **re-requests instances 1–10** (logged `skipped=1`), leaving the tail short → `INCOMPLETE_SERIES … filling pagination gap` → a full `_scan_existing_files` re-scan + an extra round-trip. **16 occurrences today (12× expected=11, 4× expected=21), 0 data loss** (gap-fill recovers) but every N≡1 (mod 10) series pays it. The code comment at `:1726` claims correct alignment; the alignment is to head index 0, not the tail.

**B3 — Home-panel thumbnail load: main-thread decode + slow-server tail. 🔴 (perceived "blank panel" on a fresh study).**
Per-card `base64`/`QPixmap` decode on the GUI thread (`right_panel_widget.py:652-695`) for a study with many series, plus a fetch bounded only by the 30 s timeout and a 4-call fallback chain. For a not-downloaded study (no local cache) the panel waits on the server, then decodes N images on the UI thread.

**B4 — Multi-study import re-scans DICOM headers off disk. ⚠️.**
The DB-metadata fast path is excluded for multi-study (`_vc_load.py:343-345`), so the exact scenario this pipeline targets (multi-study + freshly downloaded) re-reads headers the downloader already indexed into `dicom.db`. `load_single_series_total` avg 248 ms (max 2.46 s) includes this.

**B5 — DB-write contention during concurrent download + view. ⚠️ (cross-cutting).**
`save_series_instances_total`/`batch_insert_instances_total` max **6.9 s**, `transaction_scope` max **18.6 s**, `create_connection` max **2.3 s** (pool lock wait). The download subprocess and the viewer share `dicom.db`; under a large batch write the viewer's reads can stall. Retry/backoff prevents failure but adds latency exactly when the user is dragging a just-downloading series.

**B6 — `Response too large` on a giant single instance → multi-minute failing retries → series fails. 🔴 (rare, severe).**
A 558.6 MB single instance can't shrink below batch=1 (`socket_client.py:1456`), so it does 2 same-size retries on fresh sockets (~7 s each) then **fails the series** — a ~7m45s window observed once. Server payload-cap limit; the recovery path can't succeed for a genuinely oversized image. 144 `Response too large` lines total.

**B7 — Cold decode 11–15 ms/slice + single download slot. ⚠️ (bounded).**
Cold decode is ~3× the warm KPI (benchmark); mitigated by prefetch/surrogate but a fast scrub on a cold series still incurs per-frame misses. `MAX_CONCURRENT_STUDIES=1` serializes studies, but the batch-boundary yield made handoff median 0 ms on LAN (0 exhausts) — only material on a slow link.

---

## 4. What is already optimal (preserve)

- **Open is fully off-GUI-thread** (`to_thread` fan-out), per-modality enumeration gated, GetStudyInfo single-probe.
- **First-image prime** paints the first slice in 1 round-trip (~170–300 ms) — the biggest perceived-latency win on slow links.
- **Decode/display caching:** surrogate-during-drag (0 foreground decodes), L1+L2 cache, int16 LUT W/L, grayscale no-copy render, subprocess background decode, anti-flicker coalescing — viewer half is at KPI (`first_image_visible` 5–30 ms vs <80 ms).
- **Download integrity + smoothness:** atomic `*.part`→`os.replace`, `bytearray` recv (no O(n²)), 64 MB byte soft cap, missing-only enqueue, priority handoff via batch-boundary yield (no teardown), GIL yields mid-download.
- **Caches are bounded and collision-safe** (offset-key frame keys; `study_uid`-scoped disk cache); `cache_lookup` 1 ms.
- **`sync_manifest` verdict cache** (mtime-keyed) collapses redundant disk scans across badge/open/resync/DM.

---

## 5. KPI scorecard (measured vs target)

| KPI | Target (`tests/_kpi/schema.py`) | Measured today | Status |
|-----|------|----------------|--------|
| Viewer first image visible | < 80 ms | 5–30 ms | ✅ |
| Window/level per slice | (warm < 5 ms) | 1.7 ms | ✅ |
| Cache lookup | fast | 1.0 ms | ✅ |
| Drag handoff (download) | low | median 0 ms | ✅ |
| Series import (`load_single_series_total`) | — | avg 248 ms / max 2.46 s | ⚠️ (multi-study header re-scan) |
| Cold decode per slice | < 5 ms warm | 11–15 ms cold | ⚠️ (relies on cache/prefetch) |
| Time-to-full-series (160 img) | — | ~5 s (LAN) | 🔴 (round-trip floor, B1) |
| Thumbnail panel (fresh study) | right_panel_socket_ms | 60–280 ms typ, 30 s tail | 🔴/⚠️ (B3) |
| DB write / txn worst-case | — | 6.9 s / 18.6 s | ⚠️ (B5 contention) |

---

## 6. Optimization opportunities (assessment only — no changes made)

Ranked by impact ÷ effort; all flag-gateable, none touch clinical geometry/decode correctness.

1. **Fix the prime/pagination off-by-one (B2)** — small, high-value: after the size-1 prime, advance `batch_start` so `batch_index` aligns to the tail (or fetch the prime as part of batch 0 accounting). Removes a guaranteed extra round-trip + disk re-scan on every N≡1 (mod 10) series. *Effort S.*
2. **Move home-panel thumbnail decode off the GUI thread (B3)** — route `_build_pixmap_from_thumb` through the unified memory-first `ThumbnailImageSourceService`/`make_pixmap_from_bytes` (as the sidebar already does); decode bytes in the worker, hand QImages to the main thread. Also collapse the 4-call fallback chain. *Effort M.*
3. **Enable DB-first metadata for multi-study import (B4)** — extend the `AIPACS_VIEWER_DB_METADATA` fast path to multi-study (keyed by the entry's own `study_uid`/series), removing the off-disk header re-scan the downloader already indexed. *Effort M; needs golden-compare validation.*
4. **Re-enable safe batch growth (B1)** — the real fix is server-side stable pagination (offset/cursor) so larger batches can't drop tails; then growth → ~3× fewer round-trips on large series. *Effort L (server + client); the single biggest not-downloaded latency win.*
5. **Reduce download↔viewer DB contention (B5)** — e.g. larger/looser write batching windows or a read-snapshot for viewer queries during active large writes; verify against the WAL/busy_timeout settings. *Effort M.*
6. **Bound the `Response too large` failure (B6)** — detect the oversized-single-instance case early and surface a clear error instead of ~8 min of doomed retries. *Effort S (UX) / L (true fix needs server chunking).*
7. **Warm decode for the just-dropped series (B7)** — kick prefetch for a freshly-downloaded series before the user scrubs; minor, the surrogate path already covers drag. *Effort S.*

These complement the audit's PERF-1..8 (`docs/reports/COMPREHENSIVE_AUDIT_2026-06-21.md`) and the correctness analysis (`docs/reports/PIPELINE_DRAG_EXACT_SERIES_ANALYSIS_2026-06-21.md`).

---

## 7. Responsible-area index

- Open/download-start: `_hp_patient_open.py:1093-1306`; GetStudyInfo `_hp_study_save.py:50-67`; sync decision `modules/storage/sync_manifest.py:140-477`.
- Thumbnails: home `_hp_search.py:1461-1674` + `right_panel_widget.py:652-695`; sidebar `_pw_thumbnails.py:245-343`; rebuild `:462-562`.
- Drag/drop/coalesce: `thumbnail_manager.py:616-672`; `qt_fast_container.py:850`/`_vw_dragdrop.py:198`; `_vc_load.py:1812`.
- Import/resolution + DB-metadata gate: `_vc_load.py:343-345, 419-519, 704-710`; header scan `image_io.py:1691-1774`.
- Decode/display/cache: `modules/viewer/fast/lightweight_2d_pipeline.py:1452,2152-2453,2724-2809`; `disk_pixel_cache.py`; prefetch/resume `_vc_progressive.py:108,1095-1296`.
- Download transport/batch: `modules/download_manager/network/socket_client.py:178,204,1273,1455-1478,1721-1903`; concurrency `coordinator/series_intent_coordinator.py` + `core/constants.py:88`.

_No source code was modified. Timings are from today's `user_data/logs/` (latest rotation) and `.venv` micro-benchmarks; absolute download numbers are from a fast LAN and will scale on slower links._
