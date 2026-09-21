# Unify path cost and stall audit — 2026-09-14

## Decision and scope

**Subsequent implementation:** the initial audit below was read-only. The next user-authorized
slice now implements startup listing preparation in `_pw_pipeline.py`, passes that prepared
tuple to `show_exist_thumbnails` in `_pw_thumbnails.py`, and cancels it before teardown in
`_pw_lifecycle.py`. Runtime application/VTK layout stays on GUI; only the canonical cache listing
helper runs in the existing executor. No new thumbnail engine or download route was introduced.
The owner is checked before preparation and after the await; grouped Server's early skip, Local
projection, exact cache-hit/miss decisions and existing sorting/counts remain intact. Layout is
ready before the await and never rebuilt on delivery. Five fail-before guards established the
startup defect; one adversarial failure established the arriving-image/layout risk during the
first patch draft and is fixed. Eighteen final guards include real Qt/qasync/native deletion
and cancellation failure during event-loop shutdown without aborting native cleanup.
Raised preparation errors do not become synthetic empty-cache decisions; the canonical listing
helper's pre-existing error-to-empty behavior is not changed in this slice.

Read the audit's observations as pre-fix evidence for this seam; the other GUI I/O seams remain
open. The fresh 23:16 source lap below supersedes the earlier 21:47 pre-edit launch blocker;
it provides sampled GUI evidence, not a matched performance delta. This does not close download, stress,
Advanced or packaged validation. No clinical data, live DB, runtime configuration or decoder edit.

OPT-60 remains **correctness-guarded, sampled-GUI-verified, performance/stress acceptance open**.
Do not advance consolidation on the assumption that owned timers and unified identities make
the complete workflow non-blocking. The original audit and subsequent live check are read-only;
the separately identified preparation implementation above changes runtime scheduling only.

The current dirty worktree contains ongoing independent work. The synthetic baseline is commit
`5d3c72d5`; only its two thumbnail class definitions were executed in an isolated offscreen
process with current surrounding helpers. This is not an entire historical-app comparison.
The initial 21:04 evidence is historical; the separate 23:16 receipt is the post-edit source lap.
Patient identifiers, paths and images are intentionally absent from this report and fixtures.

## Fresh source GUI receipt — recorded 2026-09-15

Source main PID 1123404 started September 14 at 23:16:05, after the final preparation edits.
The human launched and signed in. No restart, hot reload, installed executable or authentication
automation was used. Existing control-client `ping` failed with QLocalSocket connection error;
no callable aipacs-control connector was available. Native observed mouse input was used instead;
the test gateway was not enabled or replaced. Exact UID introspection remains unverified this lap.

Sampled visible workflow PASS:

- Server-linked grouped sample: seven sidebar series, one previous exam, selected eight-image
  Home card opened by actual double-click; real wheel changed displayed pixels from 5/8 to 6/8.
  Normal close returned to Home. This verifies visible grouping, not authoritative person linkage.
- Local cached sample: eight cards; double-click on the non-first Series 3 opened its 25-image
  stack at 13/25. Actual wheel changed pixels to 14/25. Normal close/reopen restored Series 3,
  25/25 card count and rendered 13/25, with no observed duplicate viewport replacement.

Preparation markers, deduplicated across app/viewer/download rotations:

| Time (September 14) | Workflow | scan_ms | prepare_wait_ms | Listing count |
| --- | --- | ---: | ---: | ---: |
| 23:20:32 | Grouped Server early skip | 0.00 | 0.07 | 0 (intentional skip) |
| 23:22:12 | Local cached open | 3.90 | 358.88 | 8 |
| 23:25:39 | Same Local cached reopen | 2.26 | 319.21 | 8 |

`prepare_wait_ms` starts after GUI layout creation and includes executor queue/read and event-loop
delivery; it is neither disk-only latency nor click-to-first-image time. The approximately
317–355 ms outside the scan is not localized by these two fields. Measure queue entry, worker
completion and GUI resume separately before blaming executor saturation or changing scheduling.

Fixed F8/F11 window: September 14, 23:16:05–23:25:50, PID 1123404, ten files read with writer/delete
sharing. There were 64 unique threshold-selected stalls: median 163.2 ms, nearest-rank p95
581.8 ms, maximum 1799.1 ms, two over one second; ten stack samples. Neither the median nor p95
is a whole-session UI latency percentile. Different cases/cache state preclude a quantitative
before/after speedup claim against the 21:04 run. No sampled GUI `get_image_files -> iterdir`
stack appeared, but this small warm/cache-available lap does not prove cold/slow-disk acceptance.

Remaining sampled boundaries include startup theme/search-field construction, tab activation,
`load_viewer_backend -> exists -> stat` (420.3 ms sample age),
`load_pooyan_filter_params_from_json -> load` (548.4 ms), and `_run_deferred_close_gc` (456.7 ms).
These are sample ages, not exclusive function durations. They support further application-side
measurement; they do not establish that server response latency caused these pauses.

No ERROR/CRITICAL records were found for this PID through 23:25:47. Native log inspection for the
same process found one non-terminal `0x8001010d` and no access violation. Windows Application
1000/1001/1002 query for the fixed window found no matching Python/AI-PACS failure event; source
process remained alive at verification. This is not historical native-crash closure.

The prior 170-test / 18-new-guard code receipt remains separate; tests were not rerun for this
documentation-only verification turn. Still open: exact UID validation via the documented control
server, cold/missing-cache and cine, close during a slow preparation with a surviving tab,
Advanced/VTK independence, real OLE drag, download retry/completion/overlap, stress and packaged
acceptance. Next performance step is bounded timing of the remaining GUI delivery/I/O seams,
followed by a fail-before guard and minimal fix, not speculative replacement of the executor.

## Live evidence: responsiveness is not yet accepted

Window: 2026-09-14 21:04:04–21:17:55, main PID 925068, source launch containing the card-effect
patch. Read nine app/viewer/download log files including rotations; constrain timestamp and PID
and deduplicate identical event records. Both F8 and F11 were armed. Results:

| Measurement | Result | Interpretation |
| --- | ---: | --- |
| F8 stall events | 81 | Not 81 crashes and not all UI callbacks |
| Median recorded stall | 176.7 ms | Conditional on the probe's stall threshold |
| p95 recorded stall, nearest rank | 958.9 ms | Not request latency or whole-session UI p95 |
| Maximum recorded stall | 4116.3 ms | Unacceptable pause remains in this workload |
| Recorded stalls > 1000 ms | 4 | Includes startup and normal workflow |
| F11 stack samples | 16 | Several samples can belong to one stall |
| SLOT_TIMING records | 0 | No tag-level percentile or pass can be inferred |
| first_series_visible records | 12 | Rerenders possible; not 12 independent opens/TTFFs |

The first attempted re-read used a sharing mode incompatible with the live writer and returned
file-access errors. Its zero counts were discarded. The successful read explicitly allows
writer/delete sharing; `tools/analysis/oneoff/unify_stall_summary_2026_09_14.ps1` reproduces the
PID/window-filtered aggregate without printing clinical data. Log rotation can remove evidence
later; the fixed receipt above records what was available at audit time.

Selected stack evidence (gap is sampler age, **not exclusive function duration**):

| Time | Sample gap | Main-thread boundary | Conclusion |
| --- | ---: | --- | --- |
| 21:06:22–25 | 824.6 → 3846.8 ms | `pipeline_manager → show_exist_thumbnails → check_and_get_thumbnails → get_image_files → iterdir` | Four successive samples locate a sustained thumbnail-directory enumeration stall on GUI |
| 21:12:18 | 409.6 ms | `_render_multistudy_grouped → _is_series_downloaded → is_file → stat` | Grouped projection still performs synchronous availability I/O |
| 21:12:20 | 1120.5 ms | `_reconcile_patient_studies_on_click → _refresh_existing_study_row → _compute_local_status_flags → is_study_printed` | UI row refresh reaches synchronous DB status work; exclusive query/lock time not measured |
| 21:17:27 | 484.5 ms | `_apply_preview_ui → _apply_loaded_series_data → exists → stat` | Preview delivery still reaches filesystem metadata checks |
| 21:04:17 | 1419.6 ms | startup `setupUi → apply_theme → notify` | Separate startup/layout/theme workstream |
| 21:06:21 | 432.0 ms | patient open → download-manager construction → `_setup_ui` | GUI construction cost, not server round-trip evidence |

Other samples include assignment-state loading, tab-logo activation, header construction and
logging `write`. Instrument exclusive time before assigning those entire gap durations to a
single function. Neither F8 nor F11 alone diagnoses disk health, antivirus, contention or network
storage. The demonstrated app defect is **blocking calls on GUI**; a slow socket-server response
is not what these thumbnail stacks show. Filesystem storage may itself be remote/slow.

The earlier sampled identity/open/scroll/close GUI receipt remains valid, but it is not a
responsiveness pass. Its no-new-ERROR interval does not contradict these stalls. Previous
attachment and `Response too large` download failures remain separate, unresolved incidents;
do not increase size limits or claim authoritative download completion from UI Ready effects.

## Synthetic A/B cost, not clinical or visible-paint acceptance

Run `.\.venv\Scripts\python.exe tools/analysis/oneoff/unify_thumbnail_cost_probe_2026_09_14.py`.
Fixtures: in-memory solid 160x120 QPixmap, synthetic identities, two objects/420 display frames,
no DICOM decoding, disk thumbnail loading, network or live database workflow. Five repetitions
per size, warmup and alternating variant order. Logging disabled. All created native cards are
deleted and checked invalid after each repetition. The 420-label check is not a cine decode test.

First run (milliseconds; medians, not a five-sample p95):

| Cards | HEAD build | Worktree build | HEAD reset | Worktree reset | Worktree native deletion median / max |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 8 | 21.852 | 23.187 | 0.061 | 0.265 | 1.981 / 2.912 |
| 50 | 153.513 | 153.917 | 0.254 | 1.168 | 11.778 / 24.822 |
| 200 | 586.112 | 642.690 | 1.145 | 4.567 | 64.072 / 102.753 |

New cards own two native single-shot timers: 16/100/400 timers for these sizes. They are not
periodic polling timers. Safety bookkeeping has a real cost, especially at large counts; the
old reset is not an equivalent safe operation because it does not retire the same effects.
Do not restore unsafe cleanup just because its microbenchmark is faster.

A repeat completed successfully with 200-card medians 503.753/519.455 ms (HEAD/worktree),
and 50-card medians 127.736/130.407 ms. Focused pytest was launched while that probe session was
still outstanding, so possible contention prevents treating it as a controlled confirmation.
The variability also rules out claiming a precise universal 9.7% runtime regression from the
first run. Use the paired raw measurements as a risk signal, not a release threshold result.

Progress coalescing probe: 10,000 submissions across 200 keys retain and deliver 200 latest
values, with one worktree flush timer. First-run submit/dispatch cost was 4.647/0.155 ms
(HEAD 4.184/0.143 ms). The delivery method is replaced by a recorder: **this measures scheduling,
not painting, real progress-signal ingress, download throughput or end-to-end latency**.

## Architecture review: what is improved and what remains expensive

- Ownership/generation cancellation and native parenting improve stale-callback safety. Latest
  progress is coalesced by series and interaction protection reduces update cadence. Keep these.
- `show_exist_thumbnails` retains its old purpose: early single-study cached display. Multi-study
  skips it in favor of grouping; Local uses authoritative DB/disk projection. Nevertheless even
  the already-shown branch counts files again, and `pipeline_manager`'s Local count also scans.
  The pipeline and helper files have no current diff against HEAD: do not label this old scan
  a newly introduced card-timer regression. Consolidating rendering did not eliminate this I/O.
- Grouped rendering calls `_is_series_downloaded`; the live `stat` sample proves this concern is
  reachable, not merely dead legacy code. Availability must be prepared outside GUI and delivered
  as an identity/version-scoped snapshot without weakening completeness semantics.
- Home `_build_pixmap_from_thumb` uses `QPixmap(path)` or decodes embedded bytes on GUI. The
  identity-only render signature avoids disk reads, but does not make pixel preparation free.
- Home immediate rendering defaults to at most 16 cards; larger sets use the existing one-row
  120 ms timer. This prevents an all-card synchronous build, but nominally needs about 6/24 s for
  50/200 rows (study headers also take ticks; actual time depends on pauses). These are scheduling
  estimates, not measured live completion times. Preserve why progressive rendering exists.
- Reset/clear/native deletion traverse owners/cards; a delayed call still runs on GUI. The
  200-card deletion maximum above exceeds 100 ms even without visible layout/VTK work.
- Progress and border flushes coalesce arrivals but process their pending set in one GUI turn.
  Generic owned-callback scheduling has no global admission bound. Ownership is not backpressure.
  A reachable callback storm or leak is not established by this audit; measure pending/active
  counts under real retries/priority bursts before changing those semantics.
- Deferred patient-close `gc.collect()` is still full GUI-thread work, not a background collector.
  Do not move it blindly to a worker: Qt/VTK finalization ownership remains a safety constraint.

Qt requires GUI objects to remain on the GUI thread; a QTimer is event-loop scheduling, not
background execution. Keep file/DB/image preparation in existing workers, immutable delivery,
and bounded native UI application on the owner thread. See official
[Qt object/thread rules](https://doc.qt.io/qt-6/threads-qobject.html) and
[Qt timer behavior](https://doc.qt.io/qt-6.10/qtimer.html).

## Next acceptance sequence under existing OPT-60

1. Guard and remove the **observed GUI filesystem seams** using the existing projection/worker
   ownership contract, not another independent thumbnail engine. Cover early single-study,
   already-shown, Local/import and grouped availability. First instrument scan/read/decode,
   dispatch delay and GUI apply separately. Preserve placeholders, offline behavior, sort order,
   duplicate/missing numbers, multi-study identity and object-versus-frame counts.
2. Give prepared UI batches an elapsed-time budget; measure first-card and all-card readiness
   together with event-loop latency. Do not replace progressive rendering with an all-card loop.
   Apply cancellation on patient change/close and verify the surviving tab remains independent.
3. Diagnose status DB/attachment I/O independently; `is_study_printed` still calls its compatibility
   column helper. Measure lock/query/migration timing before selecting a repository/cache fix.
4. Establish authoritative completion before further download optimization. Then benchmark
   viewer-only versus same-study and other-study download overlap, including retries/cancel and
   terminal delivery. The cheap synthetic coalescer is not download acceptance.
5. Run bounded stress/teardown and packaged acceptance later, keeping Fast/Advanced/VTK as separate
   execution domains. No VTK sharing, no worker-side QWidget mutation, no `processEvents()` remedy.

Every runtime slice requires fail-before/pass-after guards plus an affected-workflow source GUI
pass through the documented test MCP. Do not promote this audit's offscreen probe to a GUI pass.

| Acceptance axis | Required comparison / invariant | Current evidence |
| --- | --- | --- |
| GUI blocking | Zero synchronous FS/network/DB/decode at the changed interaction boundary | Fails in observed thumbnail/status seams |
| Interaction | Existing catalog: FAST cached display p95 <15 ms; drag UI lag p95 <200 ms; compare matched runs | Not captured adequately here |
| Thumbnail latency | First card, all cards, queue age and GUI batch p50/p95/max at 8/50/200 cards, cold/warm | Synthetic class costs only |
| Load interference | Viewer-only vs download overlap, same input/dataset/build; throughput plus interference index | Not measured here |
| Bounded resources | Queue/timers/animations/threads and RSS before/after repeated open/close; no monotonic retained growth | Per-probe deletion checks only |
| Correctness | Exact Study/Series UID, counts, representative pixels, offline/cine and retries; Fast/Advanced isolation | Prior sampled live receipt, not full matrix |
| Crash stability | Repeated heavy import/open/close during progress; source then documented packaged lane | Not certified |

## Verification and handoff

Startup preparation guard file: `tests/code/ui_services/test_pipeline_thumbnail_preparation.py`.
Final startup implementation selection: **170 passed, 6 existing SWIG warnings, 21.09 s,
exit 0**, direct pytest (`-p no:debugging --reruns 0`), including all 18 new cases, Local/collision,
multistudy, progress/lifecycle and the prior import/layout/overlay crash guards. Syntax and
scoped diff checks pass. Source GUI is pending fresh human bootstrap, not accepted by this run.
The expanded run also exposed an older progress test double without `_disposed`; initializing it
to `False` restores the existing live-manager contract. Production progress behavior was not
changed. Do not confuse that test-fixture failure with a new startup/download defect.

The original audit-only verification below is historical; the startup implementation has its
own expanded test receipt in OPT-60. Changed core mixins have no plugin payload mirrors;
read-only verifier reports 462 matching pairs. No installed build was made.

Fresh direct pytest: `test_thumbnail_card_effect_lifetime.py` and
`test_thumbnail_manager_retirement.py`, `-p no:debugging --reruns 0`, offscreen: **31 passed,
6 existing SWIG deprecation warnings, 15.84 s, exit 0**. Both synthetic probe executions exited 0.
No new GUI actions, app restart, clinical data changes, mirror changes or release build.
The earlier 441-pass result is historical and was not rerun in this audit. No runtime fix is
claimed, so no new fixed-defect Regression Catalog entry is appropriate yet.
