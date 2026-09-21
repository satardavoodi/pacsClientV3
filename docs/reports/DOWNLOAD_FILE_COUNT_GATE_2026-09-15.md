# OPT-04: series file-count gate and retry destination ownership

**19:12-19:20 follow-up:** three live MR downloads completed at 65/65, 114/114 and
72/72. Independent header/file checks found 251 unique SOPs across 21 MR series,
correct Study UIDs and no `.part` files. Three separate document tasks completed
at 1/1. Twenty-three terminal file-count checks passed at 0.76-2.78 ms; skip routes
remain separate. Patient close/reopen and rendered last-slice checks passed; stale
Preview metadata and Download Manager summary/details are recorded as open findings.
See [the full receipt and limitations](CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md).

**Latest status:** sampled fresh-source live verification is recorded below.
Normal download/end-state, pixels and wheel passed. The user subsequently confirms
patient-tab native drag/drop works; the unfinished automated attempt below remains
an automation limitation, not a reproduced app defect. In-flight progress, explicit
pause/retry, Home drag and collision/error live cases remain open. See the
[current crash/Unify/KPI audit](CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md).

## Decision

Prevent a known-count series from reporting success when fewer resume-eligible
files exist than the server metadata requires. Preserve the previously selected
UID-scoped destination during retries. This is a bounded correctness prerequisite,
not a download scheduling optimization, a UI redesign or closure of Unify/OPT-04.

The preceding socket-response slice is documented in
[the response review](DOWNLOAD_SOCKET_RESPONSE_REVIEW_2026-09-15.md).

## Evidence and root cause

`SocketDicomClient.download_series` returned `success=True` after the batch loop
regardless of missing payloads, decode/write errors, duplicate instance numbers or
an early `has_more=False`. A duplicate filename also incremented `skipped_count`
after that same file had already incremented `downloaded_count`. Consequently,
reported progress could exceed the number of unique local files.

`SeriesDownloader` trusts this result when populating completed/failed series;
`DownloadExecutor` projects study success into COMPLETED/100%. These are not
independent completeness validators. The new synthetic guard produced **12 failed,
4 passed, exit 1** before the socket correction. An earlier fixture setup error
was corrected to use the installed pydicom writer API; it is not defect evidence.

Adversarial consumer review identified a necessary adjacent correction: the first
attempt uses `resolve_series_folder_name`, but retry rebuilt the path from the bare
series number. With same-number, distinct-UID siblings, retry could read the other
series' files and report false success. The real coordinator plus synthetic socket
workflow reproduced **2 failed, 21 passed, exit 1** before changing the coordinator.
Both failing cases were same-number retries (recovering and still-incomplete).
This defect predates this slice; increased truthful failure reporting would expose it.

These are deterministic client defects, not proof that the latest live session
actually lost files. The earlier ten-broadcast error and sampled GUI-side DICOM
window-level read are separate causes; this change does not claim to remove that
GUI stall or QtWebEngine cold-start time.

## Implementation and preserved boundaries

- Socket client: duplicate responses do not add another skipped file. At normal
  series-loop termination, call the existing resume-file scanner once through
  `asyncio.to_thread`; compare its count with the expected instance count.
  Too few files produce a failed `SeriesDownloadResult` with numeric
  `Incomplete series: present=... expected=...` detail, allowing existing retries.
- Cancellation remains distinct and is checked again after the final scan, so a
  late cancellation cannot become success. Scan failures represented by the
  existing helper's empty result cannot pass a positive expected count.
- Coordinator: remember the first-path destination by SeriesInstanceUID and reuse
  it for retry. Do not implement a second folder resolver, migrate existing files,
  or change normal naming, collision suffixes or metadata ordering.
- Add one aggregate `[SERIES_FILE_COUNT_CHECK]` log record with expected/present
  counts, outcome, cancellation and check duration. No new payload/identifier log,
  per-image signal, widget update or GUI-thread scan is introduced.
- Both existing plugin payload mirrors were synchronized by the repository tool.
  No new dependency, schema, flag, module/catalog entry or packaging profile.

Unchanged: wire protocol/authentication, base64/gzip/VM normalization, transfer
syntax and pixels, atomic writes, batch indexing/size/pacing, retry budgets,
priority/preemption, progress-event shape, frozen denominators, UI layout and
Fast/Advanced/VTK domains. Valid partial files remain available for retry; no
patient data or live database was modified by the tests.

## Limits: this is NOT a durable completion certificate

The gate is a lower bound using the **existing** resume eligibility (DICOM suffix,
minimum file size, exclusion of `.part`). It does not decode files, verify SOP UID
membership/uniqueness, validate pixels, prove DB convergence or certify persistence
after power loss. Extra unrelated or corrupt-but-large files remain a limitation
of the existing scanner. Expected counts are instances, not cine frame counts.
The existing zero-count metadata behavior is intentionally preserved, not promoted
to evidence that an unknown/empty series is clinically complete.

Checks apply to normal socket-series termination. Existing already-complete skip
routes retain their separate resume rules. Therefore neither this marker nor 100%
progress is authoritative study-wide disk/manifest proof. The frozen manifest,
all ingress/skip routes and durable completion marker still need their own guarded
workstream before further download scheduling optimization.

The additional work is one O(files) enumeration per terminal series attempt,
outside the event-loop thread, not an enumeration per image or UI refresh. No
live latency improvement is asserted. Use `check_ms` in a fresh source session
to measure its cost on actual storage; slow/network storage and whole-app drain
remain separate acceptance concerns.

## Verification

- New guard: `tests/code/download_manager/test_series_file_completion.py`, **23
  passed**, including missing/empty/malformed/gzip/short/duplicate/write failures,
  file retention and resume, byte preservation for plain/gzip transport, scan
  failure, one off-loop final scan, late cancellation, preserved zero metadata and
  real coordinator success/failure propagation with same/different series numbers.
- Expanded direct pytest selection: **217 passed, 6 existing SWIG warnings,
  exit 0**, 5.32 seconds. Includes the 23 cases, previous socket/large-batch guards,
  Overall Progress, UI initialization, resume/retry retention, priority/yield,
  cancellation, worker cleanup, multi-study/folder identity and state-store tests,
  plus five builder/registry/parity guards. This is a focused suite, not all tests.
- Mirror verification: **465 matching pairs, zero plugin-only files**, exit 0.
- Existing removed payload-key/tolerant-text helper failures remain baseline debt
  as recorded in the response review. They were not hidden, restored or declared
  passing. Historical pagination/gap-fill source expectations are not implemented
  by this gate. No full installer build or installed acceptance was performed.

## Required source GUI gate and next step

The documented local control client successfully answered ping and list_actions.
The running source session still started at 15:43:24, before these changes. Do not
hot reload or count mixed old/new process state as acceptance. Human fresh source
launch with the test server, disk notice OK and human sign-in are required.

Then exercise an authorized nonclinical multi-series download: queue/details
Overall Progress, actual local instance counts and rendered output, pause/resume,
retry retaining files, and a verified same-number/distinct-UID case when available.
Correlate the new count-check records and terminal state in that session. Do not
inject failures into the clinical PACS or cancel an unrelated download. Ordinary
success alone does not reproduce early-end or collision-retry faults; synthetic
guards supply that evidence. Source GUI is **pending**, not passed.

After acceptance, investigate the separately sampled GUI DICOM window-level read
with existing metadata/cache authority and fail-before latency/identity guards.
Do not combine that viewer change with further download scheduling changes.

## Fresh source sampled live receipt (16:51:38 launch)

The user explicitly requested source launch; no old main.py process was present.
One venv redirector/main pair started at 16:51:38, main PID 1169344, followed by
human sign-in. This supersedes the old-process blocker above, not every workflow
gate. No installed executable or additional source instance was launched.

The documented client answered ping then list_actions. Native Computer Use
confirmed Home and an empty Download Manager. One day's MR search was submitted
through the existing local client; a verified single-study row was selected and
its Home thumbnail was opened by an actual double-click. Identifiers and paths
were retained only in transient local test state, not in this receipt.

Observed results:

- Exact target study and first SeriesInstanceUID matched the viewer metadata;
  the first stack displayed pixels with 24 slices. Native wheel moved 13/24 to
  14/24 and visibly changed the image.
- Five MR series completed with counts 24, 24, 20, 24 and 25 (117 total). Independent
  enumeration of the observed study directory found exactly those counts and no
  `.part` files. The directory study identity matched the selected study.
- A related document download was a separate 1/1 task, not a sixth MR series.
  Six count-check records passed: the MR five plus that document. Check durations
  were 1.89, 2.22, 1.93, 2.26, 2.55 and 0.97 ms. The document's pixels/SOP validity
  were not verified. Early thumbnail metadata counts included zeros and are not
  used as the independent count oracle.
- Native Download Manager selection showed COMPLETED and 117/117 in the queue;
  the right-hand Overall Progress also showed 117/117, with 5 series / 117 images.
  This verifies terminal agreement, not sampled monotonic in-flight progression.
- Native drag of the second card entered an unfinished drag state; the second
  viewport stayed empty. Escape cancelled it cleanly. This is NOT a drag pass or
  proof of an app regression: tool release fidelity versus app handling remains
  unresolved. The separate documented `change_series` route then rendered that
  exact second SeriesInstanceUID in viewport 1, 24 slices, preserving viewport 0.
- A download-child ERROR record at 17:00:20 was `Download cancelled (preemption)`;
  the next coordinator record classified it as paused for higher priority. Later
  task/count/UI convergence succeeded. Do not count this as a native crash or
  silently claim an entirely error-free download log. Cancellation log severity
  remains separate existing debt.
- The selected completed row still displayed a prior nonzero speed / unknown ETA
  in its detail area while the queue speed was zero. This is a minor stale display
  observation, not evidence of continuing download or proof that this slice caused it.

Scoped F8/F11 records from 17:00 through the captured 17:04:11 tail: 10 threshold-
selected stalls, median 241.8 ms, maximum 498.9 ms, none over 1 second. This small
workload is not comparable to earlier whole-session percentiles. A 416.6 ms sampled
stack at 17:02:26 reached `get_rendered_frame -> _render_frame_uncached ->
_get_pixel_array -> _decode_slice -> pydicom.dcmread` on the GUI path. This is a
separate first-frame/cache-miss investigation, not time spent in the new final
file-count scan. Earlier cold Home construction reached 1658.8 ms; first DM open
also had a 446.9 ms sampled trace. No blanket freeze/performance closure.

Native diagnostics contain one `0x8001010d` record in this main session's startup
section; the same process continued through all tests, so it was non-terminal.
No new access-violation record was observed in the inspected new-session sections.
This is not a whole-app shutdown/crash soak pass; the app was left running.

No new runtime change was made during this live lap. Still pending: native drag
completion, intentional pause/resume/retry, same-number distinct-UID recovery,
early-end/broadcast injection (synthetic only), full SOP/durable manifest proof,
and packaged acceptance. Next code investigation should trace the GUI cache-miss
decode and its worker/cache lifetime before proposing a viewer change.

## Rollback

Undo only this slice's final count check, duplicate accounting and coordinator
destination map, then synchronize their payloads. Preserve the earlier response
framing fix and all unrelated dirty work. No schema or file-layout migration is
needed. Retain this evidence and guards; rollback would restore the known risks.
