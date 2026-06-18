# Perceived-Latency / Responsiveness Investigation (2026-06-18)

**Question:** the workstation must feel stable/responsive under unstable internet, and smooth on
a fast LAN. Backend ms look good — so where does the *perceived* instability come from?

**Method:** log analysis (`MAIN_THREAD_STALL_TRACE`, `FAST_OPEN_TRACE`, `UX_*`, stage-timing) on
today's session; a read-only GUI-thread-blocking map of the open/thumbnail/search/drag paths;
plus the live GUI tests from earlier today (single/double-click, drag matrix, multi-study 46713,
not-downloaded 47102).

## TL;DR — the hidden bottleneck is STARTUP, not the pipeline

1. **In-workflow, the GUI thread is never blocked by the network.** Thumbnail fetch
   (`_hp_search.py` → `asyncio.to_thread`, 45 s budget), patient search (`asyncio.to_thread`),
   study/series metadata (`asyncio.to_thread`), and drag-drop (worker threads + coalesced
   intents) all run off the GUI thread. The download itself is a separate subprocess. Result:
   under slow internet the UI stays responsive (spinner/progress visible) while data arrives.

2. **The post-transfer load chain is fast.** `UX_FIRST_IMAGE_VISIBLE total_ms` today =
   **16–165 ms** (decode 0–19 ms). Showing the first slice after data is on disk is not a
   bottleneck — including the 4-page DOC (165 ms) and a 90-image series.

3. **Every multi-second main-thread freeze is at SESSION STARTUP:**
   - License validation: `LicenseManager.check_license()` → `validate_license()` is called
     **2–3× at startup** across separate instances (`main.py:1197` + `:1209` enforcement,
     `app_handler.py:768` display) and is **uncached** — each pays the full cost.
   - Single-instance takeover: psutil process-tree enumeration (`exe`/`pids`/`children`) on the
     GUI thread — ramps to **7–8 s** in the traces.
   - License-label display (`_update_license_info` → `setVisible` → `notify`) and the
     Secretary/EchoMind orb's **one-time 121-frame build** (`_rebuild_frames`, ~3.5 s on first
     paint at a new size; already guarded to not rebuild per-paint).
   - Worst observed: a **13.4 s** `notify` freeze at an 11:46 relaunch.
   These are **outside** the download/thumbnail/drag/viewport pipeline, and inside
   safety/startup systems (license + single-instance).

4. **Slow-internet residue is worker-thread DATA latency, not GUI freeze.** On a poor link:
   `search_patients_sync` runs **once per modality, sequentially** for multi-modality patients
   (sum of latencies, not max); the right-panel thumbnail fetch has a **3-call fallback chain**
   (get_study_thumbnails → query_series_thumbnails → get_study_info), each with a long timeout.
   The GUI never freezes, but useful data can arrive later than necessary.

## Acceptance-criteria status (from the requirement)

| Criterion | Status | Evidence |
|---|---|---|
| Quickly see metadata/thumbnails/progress under unstable net | **Met** | metadata resolved up front (`all_studies=2` at open), thumbnails cache-first (72% hits) + offloaded fetch, progress text + persistent spinner |
| Drag-drop shows first useful image ASAP | **Met** | first-image prime fires (verified); `UX_FIRST_IMAGE_VISIBLE` 16–165 ms |
| Viewport never blank without explanation | **Met** | persistent loading lifecycle (never blanks while awaiting) + progress/identity text |
| Received data stays visible during interruption | **Met** | loading-persist + disk-ready resume; no unnecessary viewport reset |
| Impatient re-drag doesn't destabilize priorities | **Met** | global view-intent coalescing (last-write-wins, 350 ms) |
| Fast-LAN large image without perceived lag | **Met (post-transfer)** | post-transfer 16–165 ms; *but see startup freeze* |
| Unified pipeline remains the single path | **Met** | resolution + payload + metadata sink + thumbnail disk source all single-authority |
| **App never feels frozen** | **NOT met at startup** | 7–13 s startup GUI freeze (license + single-instance, §3) |

So the in-workflow requirements are already satisfied by the existing design; the gap the user
feels is the **startup freeze** (and, on a poor link, slightly-late data — not a freeze).

## Prioritized fix plan (each flag-gated, behaviour-preserving, needs live validation)

**P1 — Startup freeze (highest perceived-stability win; SAFETY-SENSITIVE — needs go-ahead).**
- **Memoize `validate_license()` for the startup window** (module/class-level cache keyed by
  license_key, short TTL). Returns the *same* result; enforcement byte-identical; removes the
  2nd/3rd redundant ~Xs call. Lowest risk of the P1 set.
- **Off-thread the display-only label** (`app_handler._update_license_info`): run the check in a
  worker, update the label via signal on the GUI thread. Verified display-only (enforcement is
  `main.py`), so login is unaffected; the form is usable immediately.
- **Bound the single-instance psutil scan**: filter candidate processes by name **before** the
  expensive per-process `.exe()`/tree walk. Preserves takeover behaviour; cuts the 7–8 s scan.
- **Lazy/async Secretary orb frames**: build the inactive + first active frame up front, the
  remaining 120 on an idle timer / worker. Removes the ~3.5 s first-paint build.

**P2 — Slow-internet data latency (worker-thread; GUI already responsive).**
- **Parallelize per-modality `search_patients_sync`** (`asyncio.gather`) so a multi-modality
  open costs max(modality) not sum. Touches the guarded multi-modality enumeration — live
  multi-study validation required.
- **Shorten / parallelize the right-panel fallback chain** timeouts so a placeholder + first
  available data render sooner on a dead/slow server.

**P3 — Loading status text (low-risk UI).** Enrich the neutral phase wording (fetching
metadata → downloading first image → preparing → downloading remaining → retrying) tied to
*actual* progress. Must NOT assert connection quality (a regression test forbids "slow
connection"); keep states neutral.

## Clinical guardrails / why no blind edit here
License validation and the single-instance guard are **safety/startup systems outside the
unified pipeline**. Per the project rules (don't weaken safety checks, don't refactor unrelated
systems without care, validate before/after), the P1 changes need explicit go-ahead **and** a
live before/after startup-stall measurement. None changes enforcement, slice geometry, VTK/MPR,
or download integrity; all are flag-gated with the legacy path preserved.

## Implementation status (2026-06-18, end of session)

After reading the actual code, "everything (P1+P2+P3)" reduced to one clear safe fix plus several
items that were already handled or are clinically risky:

- **P1d — Lazy Secretary-orb frame build: DONE.** `secretary_button_widget.py` now builds the
  inactive + first active/error frame up front and streams the remaining 71 active + 47 error
  frames in 8-per-tick idle chunks (`_build_more_frames`); consumers already use
  `len(_active_frames)` so a growing list animates in range. Removes the ~3.5 s every-launch
  first-paint freeze. Flag `AIPACS_ORB_LAZY_FRAMES` (default on; `=0` = byte-identical legacy).
  Verified: py_compile clean, 30/30 secretary tests + 3 new `test_secretary_orb_lazy_frames.py`
  green; **not** plugin-mirrored (mirror set still 389/389). Live visual smoothness check pending.
- **P1a / P1b — DROPPED (license is fast).** `check_license`/`validate_license`/`get_hardware_id`
  are pure computation (sha256 + file read + `uuid.getnode` + `os.environ`; **no psutil, no
  network**). Memoizing or off-threading them saves nothing. License code left untouched. (The
  startup psutil cost is the single-instance sweep, not the license.)
- **P1c — Single-instance sweep: FIXED + live-validated (the big win).** A fresh relaunch showed
  the sweep at **~9.5 s**. Stack-confirmed root cause: on Windows psutil `name()` ==
  `basename(exe())`, so `process_iter(["pid","name"])` pays an `OpenProcess`/`proc_exe()` for
  **every** process — the 2026-06-08 "cheap name pre-filter" assumed `name()` was cheap (true on
  Linux, NOT Windows). Fix: a cheap Toolhelp32 snapshot (`_iter_pid_name_cheap` /
  `_toolhelp_pid_names`) for the (pid, name) pre-filter; matching/kill logic unchanged; psutil
  fallback; flag `AIPACS_FAST_PROC_SCAN` (default on, `=0` = legacy). **Measured live on this
  machine: 8448 ms → 49 ms for 545 processes (~170×)**, all 8 python candidates still found.
  `single_instance_lock.py` is not plugin-mirrored. Verified: py_compile clean, 14/14 takeover
  tests (2 updated/added). End-to-end confirmation on the next relaunch.
- **P3 — Loading status text: largely already built; remainder deferred.** The overlay already
  shows series identity + "Downloading N of M · P%" + a progress bar + a **neutral** connection
  state. The extra states requested ("connecting"/"retrying after interruption") need a real
  cross-layer DM retry/connection signal that does not exist yet, and the prior fix deliberately
  **forbids asserting connection quality** (a regression test bans the phrase "slow connection",
  because a series queued behind another download is indistinguishable from a slow link). Safe
  enrichment is marginal; deferred pending a real DM signal + live review of the current overlay.
- **P2 — Slow-net per-modality search parallelization: NOT done (unsafe).** Verified the patient
  service defaults to a **single shared socket client** (`use_connection_pool=False` → shared
  `self.client`); the per-modality search is sequential (`await to_thread` per modality) precisely
  because concurrent requests on one socket would desync the stream and could return **wrong
  patient data** (clinical correctness). Parallelizing is therefore unsafe by default. Genuine
  slow-net latency reduction here needs a thread-safe connection pool — an architectural change,
  out of this scope. Deferred; no edit made.
- **Remaining startup cost (~2.4 s): home-page construction** (`MainWindowWidget` →
  `add_AIPacs_tab` → `ControlPanelInterface`), spread across the patient table / panels / toolbars.
  Not one bottleneck; deferring widget construction is a larger refactor with regression risk —
  documented, not churned.

### Net startup result
With P1c (sweep 8448→49 ms) + P1d (orb ~3.5 s → lazy), the measured startup main-thread freeze
drops from **~15 s to ~2.5 s** (the residual being home-page construction). Both fixes are
flag-gated, reversible, test-covered, and (for single_instance) not plugin-mirrored.

## Cross-type KPI consistency + stability (live, 2026-06-18 ~19:23, post-fix relaunch)

Measured on the running source build, multi-study patient 46713 (MR Study 1 = 34 series + DOC
Study 2 = 1 series), fully downloaded. Wall-clock from FAST_OPEN_TRACE / UX_* / VIEWPORT_LIFECYCLE.

| Action | KPI | Note |
|---|---|---|
| Relaunch startup | **no psutil sweep stall** (was ~9.5 s) | P1c validated end-to-end |
| Open (double-click → first series) | **1.42 s** | `all_studies=2` resolved up front; both studies `download_skipped_complete` (on disk); `tab_created` 1.15 s is the variable part |
| Drag → first image — localizer (12 img) | **56 ms** | render only |
| Drag → first image — ep2d (90 img) | **20 ms** | **same as the 12-img series** — viewer shows the first image immediately, not the whole series |
| Drag → first image — DOC (2200×1598) | **165 ms** | document raster |
| Thumbnails (cache) | **190–500 ms** | scales with count (7→28 thumbs) |
| Thumbnails (server) | **740–1600 ms** | scales with count (6→34 thumbs) |
| Close (tab teardown) | **~423 ms** | sub-second GUI block (`close_tab_requested`) |
| Errors/exceptions during the battery | **0** | clean ViewportLoadRequested→Cleared lifecycle; no `cross_patient_skip`, no DB lock |

**Conclusion — the consistency goal is already met for the interactive layer.** Drag→first-image
and first-image render are **consistent and fast (20–165 ms) regardless of series image count or
type** (MR vs DOC) because the viewer paints the first image immediately rather than waiting for
the full series — a 90-image series loads as fast as a 12-image one. Thumbnail KPI is consistent
per (source, count). The remaining variances are **not type-specific instability**:
- **Viewer-tab construction** (`tab_created` 431–1155 ms) and **home-page/theme construction**
  (~2.5–4 s at startup) — UI build cost; deferring it is a larger refactor (regression risk).
- **Download time** for not-yet-downloaded series — inherent (network × size), already mitigated
  by the first-image prime + progressive feed (first slice shown while the rest streams).
- **Close teardown** ~423 ms — sub-second GUI block.

No KPI-inconsistency or stability defect was found that warrants a code change; the pipeline
already normalizes the interactive KPIs and the workflow ran error-free. The three sub-second/
few-second UI-construction costs above are the only remaining targets and each is a larger,
separately-validated refactor rather than a minimal-safe edit.

## Open items (blocked on app focus / access)
- Live visual check of the lazy orb animation; live before/after startup-stall capture; the
  large-study (224-image) drag measurement; and the P2 slow-net work — all need the source app
  focused and computer-use access re-granted (the approval dialog timed out this session).
