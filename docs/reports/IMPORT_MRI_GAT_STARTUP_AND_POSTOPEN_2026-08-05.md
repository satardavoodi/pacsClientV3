# MRI GA T import slowness, startup freeze & post-open stalls — 2026-08-05

**User report:** "Evaluate the import process for this link
`C:\Users\Dr.Alizadeh\Downloads\MRI GA T\MRI GA T\DICOM\PA000000\ST000000`.
The import process is slow, and after opening, the patient seems to make the
app slow. Checking the log, it seems to be still the problem of the patient
list loading in local mode."

**Session under analysis:** pid 193888, source build, 2026-08-05 20:35:08 →
20:38:50 (app start → patient Tonkikh G A fully open). Evidence: `app.log`,
`viewer_diagnostics.log` (MAIN_THREAD_STALL probe + F11 stack sampler),
`db_diagnostics.log`; probes in `_recovery/probe_gat*.py` / `gat*.txt`.

---

## 1. Ground truth about the import source

384 files / 66.3 MB / 8 MR series (SE000000:3 … SE000005:90 …), **all**
`1.2.840.10008.1.2.1` Explicit VR Little Endian. **Compression plays no role
in this import** (`converted=0` — the decompress-on-import path never ran).
Copying 66 MB disk-to-disk should take a few seconds; it took 40.9 s, and the
GUI was frozen for most of the whole 3.5-minute window. Three independent
main-thread blockers did that, all now root-caused to exact code lines.

## 2. Measured timeline

| When | Phase | Wall | GUI thread | Cause |
|---|---|---|---|---|
| 20:35:08–59 | app start → main window shown | 51 s | 5.9 s + **18.5 s** stalls | login-window construct; then `mainwindow_construct ms=18043` / `home_widget ms=14203`, of which **~11.5 s in `gethostbyaddr`** → **GW-1** |
| 20:36:16–20 | `[IMPORT_SCAN]` | 3.2 s | ok (worker + modal) | fine |
| 20:36:23–20:37:04 | `[IMPORT_COPY]` 384 files | **40.9 s** | **39.7 s contiguous stall** | browser prewarm Chromium construct on GUI thread + 152 MB warm read contending with copy I/O → **IMP-1** |
| 20:37:04–14 | study registration (DB) | 10.6 s | **10.6 s stall** | full-file `dcmread` ×384 + inserts on GUI thread → **IMP-2** |
| 20:37:14–30 | thumbnail prep, list refresh | ~16 s | serial 1–3 s stalls | open item (§6) |
| 20:37:30–20:38:24 | PatientWidget open → first drag | ~54 s | serial 1–4 s stalls | open item (§6) |
| 20:38:24–38 | first series display (series 6) | 8.4 s + 2.5 s + 1.4 s | 9.0 s stall | open item (§6): triple switch, `widget_creation_ms=5423`, `filter=2852 ms` |

## 3. GW-1 — startup: Agent Gateway bind does reverse-DNS on the GUI thread

The F11 sampler shows the main thread inside
`hostname, aliases, ipaddrs = gethostbyaddr(name)` continuously from
20:35:45.5 to 20:35:56.5, ending exactly at `[AGENT_GATEWAY] HTTPS listening
on 0.0.0.0:8760` (20:35:57.06). Chain: home-widget construction →
`agent_gateway.service.start()` (synchronous, GUI thread) →
`GatewayHttpServer.start()` → `ThreadingHTTPServer(...)` constructor →
stdlib `HTTPServer.server_bind()` → **`socket.getfqdn("0.0.0.0")`** → PTR
lookup the clinic DNS never answers → ~11.5 s hang. Only `serve_forever`
was on a background thread; the bind was not.

**Fix:** `_FastBindThreadingHTTPServer.server_bind` = stdlib bind minus the
`getfqdn` call (`server_name` is never used by our handler). Flag
`AIPACS_GW_FAST_BIND`, default ON.

## 4. IMP-1 — import: browser prewarm fired mid-import and built Chromium on the GUI thread

The OPT-22 idle gate counts only discrete input (click/key/wheel). The user's
clicks inside the NATIVE folder picker never reach the Qt event filter, and
waiting on the scan/preview modals produces no input — so at 20:36:17, one
second after `[IMPORT_SCAN] start`, the gate logged
`idle 11405ms >= 5000ms after first interaction -> warming now`.
`_warm_webengine_files` then read **152.1 MB in 4952 ms** off-thread — against
the import copy's disk I/O — and `construct.emit()` landed
`_construct_warm_view()` (QWebEngineView + `setUrl`) on the GUI thread at
20:36:23.7, exactly as `[IMPORT_COPY]` began. Result: **one contiguous
39.7 s MAIN_THREAD_STALL** (probe line 20:37:03.417, F11 sample
`view.setUrl(QUrl("about:blank"))` at 20:37:03.29) spanning the entire copy,
and the copy itself crawling at ~1.6 MB/s from the same contention.
prewarm.py's own comment records a 17 s version of this on 2026-07-23 —
the idle gate fixed the startup case but not the modal-wait case.

**Fix:** `_app_is_busy()` (modal/popup widget open) is treated as activity in
`_check_idle`, also gates the `waited`-keyed "user away" branch (zero-input
CD auto-import would otherwise still trip it), and `_on_construct` defers in
2 s steps while busy (bounded at 10 min → skip this session). Flag
`AIPACS_BROWSER_PREWARM_BUSY_VETO`, default ON.

## 5. IMP-2 — registration re-read every file IN FULL on the GUI thread

After `[IMPORT_COPY] done` (20:37:04.2) the import flow calls
`save_complete_study_info()` per study directly on the GUI thread
(`_hp_import.py` post-copy loop). For every series it globbed the copied
files and did `dcmread(str(dcm_file))` — a FULL parse including PixelData —
just to extract SOPInstanceUID / InstanceNumber / Rows / Columns / WW / WC
for `insert_instances_batch`. db_diagnostics shows the whole insert chain on
`thread_role=main` (incl. `insert_patient` 988 ms), and the F11 sampler sat
in pydicom's `fp = open(fp, 'rb')` from 20:37:06 to 20:37:13. Total:
**10.6 s MAIN_THREAD_STALL** (ended 20:37:14.744).

**Fix:** the per-file read is factored into
`_read_instance_record_for_import()` using `stop_before_pixels=True` +
`specific_tags=[...6 tags...]`. All six tags live in header groups, so the
extracted values are identical (equivalence-tested, incl. multi-value WW/WC
and missing-tag defaults); the read drops from ~66 MB total to a few KB per
file. Flag `AIPACS_IMPORT_HEADER_ONLY_READS`, default ON.

## 6. Verdict on "still the problem of the patient list loading in local mode"

**Refuted for tonight's log — with one genuine residue.**

* All OPT-50 flags are active (defaults ON in source, no env overrides), and
  the heavy queries DID run off the GUI thread: `search_patients_local`
  3007 ms and `get_imported_at_map` 1571 ms both `thread_role=worker`
  (20:37:36–39). The OPT-50 indexes exist (`Created local patient-list query
  indexes (OPT-50)` logged at 20:37:31).
* What the user experienced as "the list won't load" at startup was **GW-1**
  (11.5 s DNS hang inside home-widget construction — the list screen cannot
  even appear) plus the remaining ~2.7 s of genuine home-widget build.
* Genuine residue: list POPULATION still runs on the GUI thread —
  F11 samples show `results_table.setCellWidget(row, COL['status'|'select'],…)`
  bursts (patient_table_widget.py:4165/4454) inside 1–3 s stalls after the
  post-import refresh. And the `search_patients_local` query itself costs
  3.0 s (worker, but it delays list content). Both are tracked open items,
  NOT the old O(N²) regression.

## 7. Post-open slowness — root-caused (fixes proposed, NOT yet applied)

### 7.1 VS-1: every series drop runs THREE switches and builds THREE bridges

Confirmed on BOTH drops tonight (series 6 and series 2 — same shape, so it
is structural, not first-open noise):

1. Drop → placeholder switch with **slices=1** (`_start_qt_viewer: slices=1
   mid=0` — the FAST yield path's quick view; fine by design).
2. The on-demand load completes → **TWO independent callers each run a full
   `_perform_series_switch_optimized` ~6 ms apart**:
   * caller A — `_vc_load._apply_loaded_series_data` (viewer loop; its
     cheap `inplace_fast_sync` branch requires progressive mode, which a
     local complete series never has → full switch),
   * caller B — `_vc_switch.change_series_on_viewer`'s async-load
     completion fallback (`finish_action=fallback_switch`, ~line 1132;
     `_already_applied` is False because the viewer still shows the
     preview placeholder).
   Both hit `[QtFastContainer] switch_series: volume behind … rebuilding
   (not skipping)` back-to-back (20:38:36.007 / .013 for series 6;
   20:38:50.177 / .183 for series 2). Re-entrancy interleaves them: B
   finishes first (bridge `b3f110`, 1352 ms), then A resumes, UNLOADS B's
   200 ms-old bridge and rebuilds an identical one (`b3c7d0`, 2456 ms) —
   pure duplicated work + bridge churn. Series 2: bridges `b3f890` →
   `b97250` → `b3cb90`, three `first_image_visible` renders of the same
   slice. The phase-attribution race (both `widget_created` phases logged
   under B's switch_id; A's summary shows `widget_creation_ms=-1`) proves
   the shared current-switch state is being overwritten mid-flight.
   Cost tonight: +3.8 s on the first open, ~+250 ms and 2 wasted bridges
   on every later drop.
   **Proposed fix (VS-1):** an in-flight/just-completed switch registry
   keyed `(viewer_id, series_number, instance_count, preview_flag)` —
   `_perform_series_switch_optimized` skips an identical non-preview
   switch that is in flight or completed < ~500 ms ago. Flag-gated,
   default ON.

### 7.2 VS-2: first-use lazy imports run on the GUI thread during the first drag

* First-frame `filter_ms=2852.6` is **`import cv2`** —
  `opencv_filter_pipeline.py:45` imports OpenCV lazily inside the filter
  call, so the DLL load happens on the GUI thread at first render (slice 0,
  128×128; every later frame: 0.3–1.2 ms).
* `widget_creation_ms=5423.5` for the FIRST viewer is the same shape:
  first `QtFastContainer` + qt-viewer-bridge + decode-service infra
  (`[B3.11] Decode service started` appears only at the rebuild). Later
  widget creations: 278.5 → 78.7 → 24.9 → 5.9 ms.
  **Proposed fix (VS-2):** pre-warm at patient-open (off the first-paint
  path): import cv2 on a daemon thread + optionally build one throwaway
  pipeline/bridge, mirroring the DM linecache warm and browser-prewarm
  patterns. Flag-gated, default ON.

### 7.3 Still open (attribution pending — no owning log lines)

* The `os.stat(self, follow_symlinks=…)` main-thread runs (20:37:59–20:38:09
  and 20:38:16–24, RSS climbing 570→960 MB, CPU 10–42%) and the
  `results_table.setCellWidget` bursts (home-list population,
  `patient_table_widget.py:4165/4454`). ZetaBoost ACTIVE/INACTIVE toggles
  and `on_tab_activated` H7 folder counting bracket the windows
  (20:37:55 / 20:38:09 / 20:38:14) — candidates: per-series thumbnail/disk
  reconciliation and list-row widget population. Needs a targeted probe
  (e.g. temporary stack dump at stall > 1.5 s) or code-path instrumentation.
* `search_patients_local` 3007 ms (worker) and `insert_patient` 988 ms.
* Minor: a 401 credential refresh at 20:37:53; `[PREWARM] spawned idle
  download subprocess` at 20:37:32 (DM prewarm was ON in this run).

## 8. Changes shipped (all default-ON, independently gated)

| ID | File | Flag (kill switch) |
|---|---|---|
| IMP-1 | `modules/web_browser/prewarm.py` — `_busy_veto_enabled` / `_app_is_busy`; `_check_idle` busy-refresh + away-branch gate; `_on_construct` bounded deferral | `AIPACS_BROWSER_PREWARM_BUSY_VETO=0` |
| IMP-2 | `PacsClient/.../home_panel/_hp_study_save.py` — `_read_instance_record_for_import()` (header-only read), loop rewired | `AIPACS_IMPORT_HEADER_ONLY_READS=0` |
| GW-1 | `modules/agent_gateway/http_gateway.py` — `_FastBindThreadingHTTPServer`, `start()` class selection | `AIPACS_GW_FAST_BIND=0` |

**Tests:** 52 new guards —
`tests/code/agent_gateway/test_gw_fast_bind.py` (fast bind never calls
`socket.getfqdn`; stdlib-does reproduction pin; live HTTP roundtrip through
`GatewayHttpServer`; subclass overrides only `server_bind`; flag parsing),
`tests/code/web_browser/test_prewarm_busy_veto.py` (offscreen harness driving
the REAL `_check_idle`/`_on_construct`: busy never warms even on a perfect
idle gap; away-branch veto; kill switch reproduces the warm-under-modal
defect; construct defers / skips past deadline / runs when clear; real modal
QDialog `_app_is_busy`; source pins),
`tests/code/dicom_media/test_import_header_only_reads.py` (header-only ==
legacy full read on synthetic DICOMs incl. multi-value WW/WC + defaults;
`stop_before_pixels`/`specific_tags` kwargs pin; kill switch = plain call;
wiring pin). Regression: full `tests/code/agent_gateway` + `web_browser` +
`dicom_media` = **165 passed / 0 failed**.

Expected effect on tonight's timeline: startup home-widget ~14.2 s → ~2.7 s;
import copy ≈ disk speed with a live UI (no 39.7 s freeze); registration
10.6 s → well under 1.5 s (988 ms `insert_patient` remains, one-off).

## 9. Live-verify checklist

1. Restart the app on the clinic network → `[STARTUP_STAGE] stage=home_widget`
   should drop by ~11.5 s; no `gethostbyaddr` F11 samples; gateway still logs
   `HTTPS listening on 0.0.0.0:8760` and the phone app still pairs/connects.
2. Re-import a DICOM folder → during `[IMPORT_COPY]` no `[MAIN_THREAD_STALL]`
   ≳ 2 s; UI responsive; "browser prewarm" must never log "warming now"
   while any dialog is open (look for "construct deferred" if it was already
   in flight).
3. After `[IMPORT_COPY] done`, the registration stall should be < 1.5 s and
   the instances table must be identical (spot-check a series' rows/columns/
   WW/WC values against pre-fix rows).
4. Browser prewarm still works when truly idle: leave the app untouched with
   no dialogs → "Chromium engine warmed" appears; first browser open fast.

## 10. Change log

* 2026-08-05: probes `_recovery/probe_import_gat.py` / `probe_gat2..5.py`;
  root causes GW-1 / IMP-1 / IMP-2 fixed + gated + tested (52 new, 165 suite
  green); master plan row added. Post-open diagnosis (§7) continuing.
