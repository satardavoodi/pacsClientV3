# Drag-Drop Slow/Unstable Internet Current Recheck

Date: 2026-06-17  
Status: current-state report after the latest code changes.  
Mode: documentation/evaluation only. No runtime code was changed while preparing this report.  
Related report: `docs/reports/DRAGDROP_SLOW_INTERNET_PRIORITY_THRASH_2026-06-17.md`.

## 1. Short Answer

The latest code changes move the application in the right direction for the slow
and unstable internet drag-and-drop problem.

The current code now directly addresses the two biggest observed causes of the
client-side failure:

- The downloader can request a fresh series' first batch as one image before
  returning to the normal adaptive batch size.
- Viewer drag/drop Download Manager intent is globally coalesced, so a burst of
  repeated drops promotes only the final selected series instead of promoting
  every intermediate target.

There is also a new visible waiting state:

- The viewport spinner can show live download status text such as
  `Downloading N of M images...`.
- The awaiting-download path seeds an immediate `Downloading...` status before
  the first progress signal arrives.

However, the current implementation is not yet a complete solution.

The most important remaining issue is that the first-image prime fetches one
image early, but the viewer's first progressive display still appears gated by
the progressive grow threshold. The controller currently forces
`_progressive_grow_batch_size` to at least 5 and defaults it to 10. Therefore,
unless another live path bypasses that threshold, the first image may download
quickly and update progress text, but not actually paint in the viewport until
5 to 10 images are available.

The current state should be described as:

```text
good tactical stabilization for slow-link drag/drop
```

not yet:

```text
complete first-slice streaming and unified view/download pipeline
```

## 2. Original User-Visible Problem

At the client site, internet connectivity was unstable and frequently dropped.

Observed competitor behavior:

- The user drag-dropped a series.
- One image from that series appeared quickly.
- The application clearly showed download progress.

Observed AI-PACS behavior before these changes:

- The user drag-dropped a series.
- The viewport often showed no image while the first batch was being retrieved.
- Because the first batch was about 10 images and the connection was unstable,
  the first visible result could take a long time.
- The user repeatedly drag-dropped the same or other series.
- Repeated drops kept moving Download Manager critical priority.
- Multiple series/studies entered competing critical or retry states.
- The application appeared stuck or extremely slow, and none of the desired
  series downloaded reliably from the user's perspective.

The practical problem was not only network speed. It was the combination of:

```text
slow first visible feedback
    +
repeated impatient drag/drop
    +
single download slot
    +
priority/preemption churn
```

## 3. Current Code Improvements Found

### 3.1 First-Image Prime Exists

Main code:

- `modules/download_manager/network/socket_client.py`
  - `_first_image_prime_size`
  - `SocketDicomClient.download_series`

Current behavior:

- If first-image prime is enabled, the series is fresh, the batch size is greater
  than 1, and the modality is not already forced to single-image batches, the
  first request uses batch size 1.
- After the first batch is written and progress is emitted, the code restores the
  original adaptive batch size.
- Resume behavior is protected because the prime is skipped when existing files
  are present.

This is a good design direction because it keeps bulk transfer behavior mostly
unchanged while reducing time to first downloaded file.

Relevant flag:

```text
AIPACS_FIRST_IMAGE_PRIME
```

Default:

```text
on
```

### 3.2 Drag/Drop Download Intent Is Globally Coalesced

Main code:

- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py`
  - `_merge_drag_view_intent`
  - `_coalesce_dm_view_intent`
  - `_dispatch_coalesced_dm_view_intent`

- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py`
  - drag/drop viewed-series notification now routes through the coalescer
  - missing-series download trigger now routes through the coalescer
  - same-series incomplete retry now routes through the coalescer

Current behavior:

- Rapid drops across different series/studies are collapsed into one
  last-write-wins Download Manager intent.
- The final drop in the burst is the one that receives notify/trigger behavior.
- The view switch itself is not debounced. The user still sees immediate viewport
  response. Only Download Manager priority/download intent is delayed briefly.

Relevant flags:

```text
AIPACS_DRAGDROP_DEBOUNCE
AIPACS_DRAGDROP_DEBOUNCE_MS
```

Defaults:

```text
AIPACS_DRAGDROP_DEBOUNCE=1
AIPACS_DRAGDROP_DEBOUNCE_MS=350
```

This directly addresses the main priority-thrash complaint. It does not prevent
all repeated user actions, but it prevents a fast burst from creating a separate
critical-priority event for every intermediate drop.

### 3.3 Waiting Viewport Now Shows Download Progress Text

Main code:

- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
  - `_format_download_progress`
  - `_update_download_spinner_text`
  - `on_series_images_progress`

- `modules/viewer/widgets/loading_spinner.py`
  - `ViewportSpinner.set_status`

- `PacsClient/components/loading_overlay.py`
  - minimal overlay status label support

- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py`
  - awaiting-download path seeds immediate status text

Current behavior:

- A viewport awaiting a dropped series can show live status text based on actual
  progress signals.
- The update is intentionally isolated in try/except and should not affect
  geometry, rendering, or download behavior.

Relevant flag:

```text
AIPACS_DOWNLOAD_PROGRESS_TEXT
```

Default:

```text
on
```

This is important UX work. Even if the first image cannot appear immediately
under a hard disconnect, the user sees evidence that the application understood
the request.

### 3.4 Same-Study Priority Switching Is Less Destructive

Main code:

- `modules/download_manager/coordinator/series_intent_coordinator.py`
- `modules/download_manager/download/series_downloader.py`

Current behavior:

- Same-study critical series changes use `.critical_intent.json` so the running
  worker can yield at a batch boundary.
- This avoids repeatedly tearing down the worker for same-study cross-series
  changes.
- The existing membership validation also protects against synthetic display
  keys reaching the Download Manager.

This is a strong improvement because it changes the same-study case from
"restart the worker" toward "finish current batch, then switch priority."

## 4. Remaining Issues

### 4.1 First-Image Prime May Not Paint the First Image

This is the most important finding from the current recheck.

The downloader now fetches one image first, but progressive first display still
appears gated by:

```python
if downloaded >= self._progressive_grow_batch_size:
```

The controller initializes:

```python
self._progressive_grow_batch_size = max(
    5, int(os.getenv("AIPACS_PROGRESSIVE_GROW_BATCH", "10") or "10")
)
```

Therefore:

- The first downloaded image should produce progress.
- The spinner should update to `Downloading 1 of N images...`.
- But the viewport may not actually display an image until at least 5 images are
  downloaded, and by default 10 images.

This means the existing report text that says the first-image prime lets the
progressive feed paint a slice in one round trip is likely too optimistic.

Severity:

```text
Medium-high for user experience under unstable internet
```

Why it matters:

- The user complaint was specifically "nothing appears quickly."
- Progress text helps, but the competitor's advantage was visible first image.
- If no image appears until 5 to 10 files arrive, the user may still re-drag
  during a bad network period.

Recommendation:

For explicit drag/drop awaiting viewers only, allow first progressive display
when:

```text
downloaded >= 1
```

Keep the existing 5/10 threshold for:

- untargeted background downloads;
- non-viewed series;
- bulk progressive grow;
- performance-protection paths.

This keeps the fast first-slice behavior focused on the user's active viewport
without making every background series generate a display task.

### 4.2 Coalescing Reduces Priority Thrash But Does Not Eliminate It

Current behavior:

- A rapid burst inside the debounce window collapses to one final DM intent.
- But a user who re-drags every 1 to 3 seconds can still generate a new settled
  target each time.

Cross-study behavior remains more disruptive than same-study behavior because:

- `MAX_CONCURRENT_STUDIES = 1`.
- Cross-study priority handoff can still pause the other active study.
- A bad network can still make the user re-drag before any useful progress
  arrives.

Severity:

```text
Medium
```

Recommendation:

Add a short settled-target lock after a drag/drop intent is dispatched:

```text
after dispatch:
    keep target stable until first progress signal
    or until a short timeout expires
```

Example policy:

```text
Do not preempt the active drag target again for 2 to 5 seconds unless:
- the new target is already local/complete; or
- the current target hard-failed; or
- the user explicitly cancels/replaces it through a stronger UI action.
```

This is more protective than debounce alone because it covers slow repeated
manual drops, not just very fast bursts.

### 4.3 View Switch Is Immediate, But Local Work Is Not Coalesced

Current behavior:

- The DM priority/download intent is coalesced.
- The viewport switch attempt itself still runs immediately.
- Each drop can still show a spinner, schedule a local load attempt, do disk
  checks, or enter an awaiting-download state.

This is not necessarily wrong. Immediate viewport response is valuable. But it
means the application can still do extra local control-plane work during repeated
drops.

Severity:

```text
Low to medium
```

Recommendation:

Keep immediate visual feedback, but consider a normalized `ViewIntent` object:

```text
ViewIntent
    target viewer
    patient id
    study uid
    series uid
    original series number
    display series key
    source action: drag_drop / thumbnail / retry / open
    created_at
    replace policy
```

Then make the viewport, Download Manager, and progressive loader consume the
same intent instead of reconstructing the target separately.

### 4.4 Cross-Study Preemption Still Needs A Softer Policy

Current behavior:

- Same-study cross-series handoff can use batch-boundary yield.
- Cross-study handoff can still pause the active study because only one study
  worker is allowed.

This is safer than before because coalescing reduces how often cross-study
handoff happens, but the remaining cross-study handoff is still costly under
unstable internet.

Severity:

```text
Medium
```

Recommendation:

Implement a "settle-then-switch" policy for cross-study drag/drop:

```text
If another study holds the slot:
    record the new target as pending critical intent
    wait for current batch boundary or short grace period
    switch once to the final settled target
```

This should be part of the future unified `DownloadPlan` / `ViewIntent` work
rather than another ad-hoc Download Manager path.

### 4.5 The Current Fix Is Tactical, Not Yet the Unified Pipeline

The current code adds useful flags and guardrails, but it still leaves drag/drop,
download retry, progressive display, thumbnail selection, and patient open as
partially separate workflows.

This matters because the strategic direction is:

```text
server sync -> local catalog/manifest -> download planning -> thumbnails ->
patient open -> drag/drop -> viewport load
```

Current state:

```text
drag/drop has new local stabilizers
```

Target state:

```text
drag/drop is one consumer of the same authoritative ViewIntent/DownloadPlan
pipeline used by open, preview, retry, and backfill
```

Severity:

```text
Medium architecture risk
```

Recommendation:

Do not keep adding separate drag/drop-only rules indefinitely. Use the current
flags as a safe bridge, then fold them into the unified pipeline.

## 5. Test Evidence

Focused new-feature tests were run:

```powershell
.venv\Scripts\python.exe -m pytest `
  tests\code\download_manager\test_first_image_prime.py `
  tests\code\viewer\test_dragdrop_coalesce.py `
  tests\code\viewer\test_download_progress_text.py `
  -q -p no:debugging
```

Result:

```text
32 passed, 3 warnings
```

Broader focused drag/drop and Download Manager test set was also run:

```powershell
.venv\Scripts\python.exe -m pytest `
  tests\code\download_manager\test_first_image_prime.py `
  tests\code\viewer\test_dragdrop_coalesce.py `
  tests\code\viewer\test_download_progress_text.py `
  tests\code\download_manager\test_dm_preempt_on_drag.py `
  tests\code\download_manager\test_dm_critical_yield.py `
  tests\code\download_manager\test_unstable_internet_retry.py `
  tests\code\download_manager\test_batch_growth.py `
  tests\code\viewer\test_dragdrop_progressive.py `
  -q -p no:debugging
```

Result:

```text
84 passed, 1 failed, 3 warnings
```

Failing test:

```text
tests/code/viewer/test_dragdrop_progressive.py::test_completion_signal_triggers_one_shot_grow_on_non_progressive_viewer
```

Observed reason:

- The test replaces `_grow_progressive_fast` with a fake that accepts only three
  positional arguments.
- Production now calls `_grow_progressive_fast(..., terminal=True)`.
- The signal slot catches exceptions, so the fake does not record a call and the
  assertion fails.

Interpretation:

- This looks like test maintenance around the new `terminal=True` call shape.
- It should still be fixed because the focused suite is technically red.
- It does not appear to invalidate the new first-image prime, progress text, or
  drag coalescing tests.

## 6. Current Risk Table

| Area | Current Status | Risk | Severity |
|---|---|---:|---:|
| First image fetched early | Implemented | Viewer may not display at 1 image | Medium-high |
| Progress text while waiting | Implemented | Text only, not image display | Medium |
| Rapid burst drag/drop | Improved | Only final target promoted within debounce | Low-medium |
| Slow repeated drag/drop | Partially improved | Each settled re-drop can still preempt | Medium |
| Same-study cross-series priority | Improved | Batch-boundary yield avoids teardown | Low-medium |
| Cross-study handoff | Still costly | Single slot may still pause active study | Medium |
| Viewer switch work | Immediate | Local load/check work can still repeat | Low-medium |
| Unified pipeline | Not complete | Drag/drop still has tactical special paths | Medium |
| Test suite | New tests pass | One broader progressive test fails | Low-medium |

## 7. Recommended Solution Plan

### Priority 1: Make Explicit Drag/Drop Display At One Image

Goal:

```text
When a dropped series has an awaiting viewport, display as soon as one valid
DICOM image exists.
```

Implementation direction:

- Keep first-image prime in the downloader.
- In progressive display logic, distinguish active awaiting viewer from
  background series.
- Use threshold 1 only for explicit awaiting viewer.
- Keep `_progressive_grow_batch_size` for background/non-targeted paths.

Acceptance criteria:

- A test where `downloaded=1`, `total>1`, and `_awaiting_series_number` matches
  should call `_start_progressive_display`.
- Background series with `downloaded=1` should not start display.
- Existing large-stack performance tests should remain green.

### Priority 2: Add Settled-Target Lock After Drag Dispatch

Goal:

```text
Prevent slow repeated re-drops from repeatedly replacing the critical target
before the first target has any chance to produce visible progress.
```

Implementation direction:

- After `_dispatch_coalesced_dm_view_intent`, record active drag target.
- Hold it until:
  - first progress signal for that series;
  - hard failure;
  - explicit cancel/replace;
  - short timeout, for example 2 to 5 seconds.

Acceptance criteria:

- Five drops 1 second apart should not cause five cross-study preemptions if the
  first target is still within the settle window.
- Same-series repeated drops should remain deduped.
- Already-local series should still switch immediately.

### Priority 3: Soften Cross-Study Preemption

Goal:

```text
Cross-study drag/drop should not kill/restart the active worker for every
settled target when the network is unstable.
```

Implementation direction:

- For cross-study target changes, record pending view/download intent.
- Switch at a batch boundary or after a controlled grace period.
- Prefer one handoff to the final target instead of immediate pause-all behavior.

Acceptance criteria:

- Alternating study drops under a single download slot should produce at most one
  handoff per settle window.
- Files already downloaded by the interrupted study remain resumable.
- No cross-patient or cross-study identity leakage.

### Priority 4: Move Drag/Drop To The Unified Pipeline

Goal:

```text
Drag/drop, thumbnail click, retry, patient open, and backfill all use the same
identity and download-planning model.
```

Implementation direction:

Create or extend:

```text
ViewIntent
DownloadPlan
ViewerLoadPlan
PatientStudyCatalog
```

Then route drag/drop through:

```text
ViewIntent -> PatientStudyCatalog lookup -> DownloadPlan -> DownloadManager ->
ViewerLoadPlan/progressive display
```

Acceptance criteria:

- Drag/drop never passes synthetic display keys to Download Manager.
- Drag/drop and thumbnail click resolve the same canonical study/series identity.
- Missing/local/partial status comes from one source of truth.
- Download priority is carried as intent metadata, not inferred separately in
  multiple places.

## 8. Operational Validation Needed

The code should be validated on the client's unstable network or under a
traffic-shaped test environment.

Recommended live checks:

1. Drop a fresh not-yet-local CT/MR series.
2. Confirm log line for first-image prime appears.
3. Confirm `Downloading 1 of N images...` appears quickly.
4. Confirm whether the first actual image appears at 1 image or only after 5/10.
5. Repeatedly drag different series quickly and confirm only one final DM intent
   is promoted after the debounce window.
6. Repeatedly drag different series every 1 to 3 seconds and observe whether
   settled-target churn still blocks progress.
7. Test cross-study alternating drops while `MAX_CONCURRENT_STUDIES = 1`.
8. Confirm no synthetic display key reaches Download Manager logs.

Important log signals to watch:

```text
First-image prime
dragdrop-coalesce
dm-notify: viewed series
critical intent
series yield
series-summary
progressive: START first display
```

## 9. Final Assessment

The current code is meaningfully better than the previous behavior.

The strongest improvements are:

- first-image prime at the socket/download layer;
- global last-write-wins coalescing for drag/drop DM intent;
- live progress text on the waiting viewport;
- safer same-study critical handoff through batch-boundary intent;
- focused tests for the new features.

The remaining most important correction is:

```text
first-image prime must be connected to first-image display for explicit
awaiting drag/drop viewers
```

Without that, the user may see progress text sooner, but the first visible image
can still wait for the old 5/10-image progressive threshold.

The current work is a good Phase 1/Phase 2 tactical stabilization. It should be
followed by:

1. explicit first-image display for awaiting viewer;
2. settled-target lock for slow repeated re-drops;
3. softer cross-study handoff;
4. unification under `ViewIntent`, `DownloadPlan`, and `ViewerLoadPlan`.

