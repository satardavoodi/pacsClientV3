# Code Change Review: Multi-Study / Multi-Patient Workflow Fixes

Date: 2026-06-16

Status: review only. No application code changes were made by this report.

Related architecture review:
`docs/reports/MULTI_STUDY_MULTI_PATIENT_ID_ARCHITECTURE_REVIEW_2026-06-16.md`

## Executive Verdict

The direction of the changes is good. The code now addresses several of the
highest-risk issues from the architecture review:

- viewer multi-study display keys are translated toward canonical study/series
  identity;
- Download Manager critical intent has a membership-validation layer;
- downloader progress totals are no longer intended to depend on mutable runtime
  `series_list`;
- task-level duplicate series rows are deduplicated more aggressively;
- local attachment sync is made non-destructive;
- report-status polling has a circuit breaker;
- study completeness is moving toward the shared disk-first sync manifest.

However, the changes are not merge-ready yet. The most important issue is that
the new critical-intent validation can still be bypassed by existing public paths.
There are also failing tests and some API/protocol drift.

My practical recommendation:

1. Treat the multi-study identity patch as promising but incomplete.
2. Fix the critical-intent bypass before any build or live test.
3. Fix the failing tests and update the protocol/stubs.
4. Keep the broader reliability changes, but separate local config/generated-file
   churn from clinical code changes before commit.

## Highest-Priority Findings

### 1. Critical-intent validation can still be bypassed

Severity: high. Blocking.

The new membership validation in
`modules/download_manager/coordinator/series_intent_coordinator.py` is the right
idea. It rejects a request when the requested series is not in the task's
`series_list`.

The problem is that callers do not consistently honor that result.

In `modules/download_manager/ui/widget/_dm_priority.py`,
`request_critical_series_download()` calls:

```python
self.intent_coordinator.request_critical_series(
    study_uid, str(series_number), series_uid=series_uid
)
self._on_series_retry(study_uid, series_number, series_uid)
```

If the coordinator returns `False`, `_on_series_retry()` still runs.

In `modules/download_manager/ui/widget/_dm_retry.py`, `_on_series_retry()` can
write the `.critical_intent.json` file directly:

```python
if target_num and self._worker_is_active_for_study(study_uid):
    if self._write_critical_intent_file(study_uid, target_num):
        self.intent_coordinator.request_critical_series(study_uid, str(target_num))
        ...
        return
```

This writes the intent before the coordinator proves membership. That means the
main defense can be bypassed in the exact runtime path it is supposed to protect.

Required fix:

- Make `request_critical_series_download()` stop if
  `request_critical_series(...)` returns `False`.
- In `_on_series_retry()`, validate through the coordinator before writing the
  intent file.
- Pass `series_uid` through `_on_series_retry()` coordinator calls.
- Consider a small helper such as `validate_critical_series_request()` so direct
  intent-file paths cannot drift from coordinator policy.

### 2. UID match accepts wrong series number without normalizing

Severity: high.

In `series_intent_coordinator.py`, a request can match by `series_uid` even when
the supplied `series_number` is wrong. The validation accepts it, but the code
still stores the original wrong `series_number` in `viewed_series_number`.

Example:

```text
task contains: series_uid=U1, series_number=1
request:      series_uid=U1, series_number=999
result:       accepted, viewed_series_number="999"
```

Required fix:

- When membership matches by `series_uid`, normalize `series_number` to the
  task's actual `series_number`.
- Or reject UID/number mismatch unless an explicit migration path exists.

### 3. Public callers now have API/protocol drift

Severity: medium-high.

`request_critical_series()` now accepts `series_uid`, but the command protocol in
`modules/download_manager/ui/widget/_dm_contracts.py` still declares only:

```python
request_critical_series(self, study_uid: str, series_number: str)
```

Tests and stubs also still use two-argument lambdas. This caused existing tests
to fail.

Required fix:

- Update the protocol to include optional `series_uid`.
- Update all tests/stubs/adapters that implement `request_critical_series`.
- Keep the argument optional for backward compatibility.

### 4. New multi-study identity test file is broken

Severity: medium.

`tests/code/download_manager/test_multistudy_identity_guards.py` fails because
the helper is wired incorrectly:

```python
def _si(SeriesInfo, uid="", num="1", c=10):
    ...
```

but tests call:

```python
_si(None, "1", 10)
_si("U1", "1", 10)
```

This passes `None` or a string where the `SeriesInfo` class is expected.

Required fix:

- Either import `SeriesInfo` globally in the test, or make `_si(uid, num, c)`
  import/use the class internally.

### 5. Attachment local-first test fails due a comment

Severity: low for runtime, medium for CI.

`tests/code/network/test_attachment_local_first_persistence.py` asserts that
`"rmtree"` does not appear in `patient_sync_service.py`. The implementation no
longer calls `shutil.rmtree`, but the comment mentions the old behavior using
the literal word `rmtree`, so the test fails.

Required fix:

- Either remove/reword that literal token from the comment, or improve the test
  to inspect AST/calls instead of raw text.

## Change Area Review

## 1. Viewer -> Download Manager canonical identity

Files:

- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py`

What changed:

- Added `_DM_CANON_IDENTITY`.
- Added `_resolve_canonical_series_identity()`.
- `_notify_dm_viewed_series()` now resolves a multi-study display key back to
  actual `(study_uid, original_series_number)`.
- `_trigger_download_if_needed()` now passes the resolved `target_study_uid` and
  original series number.
- Cooldown and inflight keys now include study UID.

Quality:

Good direction. This directly addresses the biggest architecture problem: a
synthetic viewer key such as `1000003` should not reach DM/server/disk as a real
series number.

Remaining concerns:

- The resolver reads `entry["series_uid"]` but should also read
  `entry["series_instance_uid"]`, because older paths used both names.
- It falls back silently to primary study and raw series key when metadata is
  missing. That is acceptable for single-study, but dangerous for a multi-study
  display key. Consider logging a warning if the input looks like an offset key
  and cannot be resolved.
- `set_viewed_series()` in DM still does not receive `series_uid`, so the passive
  viewed-series path only validates by number. That is usually fine after
  canonicalization, but less strong than the retry path.

Effect on other parts:

- Improves multi-study drag/drop and not-yet-local series download routing.
- Reduces cross-study priority pollution.
- Can expose missing metadata in `_server_series_info` because the resolver now
  depends on those entries being correct.

## 2. Download Manager membership validation

Files:

- `modules/download_manager/coordinator/series_intent_coordinator.py`
- mirrored plugin payload copy
- `modules/download_manager/ui/widget/_dm_priority.py`
- `modules/download_manager/ui/widget/_dm_retry.py`

What changed:

- Added `_DM_MEMBERSHIP_VALIDATION`.
- `request_critical_series()` now accepts optional `series_uid`.
- If the study task exists, requested series must match task `series_uid` or
  `series_number`.
- Invalid request logs `[CriticalIntentRejected]`.
- `_dm_priority.py` passes `series_uid` to the coordinator.

Quality:

Conceptually strong, but currently incomplete because of the bypass described
above.

Important behavioral effect:

- This validation is task-list based. That works for active missing/partial
  series. But the open pipeline may queue only missing series. If the user views
  a complete series while another missing series is downloading, that complete
  series may not exist in the current task `series_list`. Rejection is probably
  safe, because a complete series does not need critical download intent, but it
  should not be logged as a scary error or as a successful CRITICAL promotion.

Recommended behavior:

- If the requested series is not in task list but is already complete/on disk,
  return a benign "no intent needed" result.
- If it is neither in task nor complete, reject as error.
- All callers should check the boolean return and log accurately.

Effect on other parts:

- Prevents phantom critical intent if enforced correctly.
- Changes the semantics of any test/stub that assumed `request_critical_series`
  always accepts any series number.
- May affect UI logs/order if completed series requests are rejected.

## 3. Immutable downloader progress totals

Files:

- `modules/download_manager/download/series_downloader.py`
- mirrored plugin payload copy

What changed:

- Added `_DM_IMMUTABLE_TOTALS`.
- Added `_progress_totals()`.
- Captures `_frozen_progress_totals[study_uid]` at download start.
- Preempted result, final result, and `_update_progress()` use frozen totals.
- Progress percentage is clamped at 100.

Quality:

Good. This is the right fix for impossible denominators caused by runtime list
mutation.

Remaining concerns:

- The yield branch still mutates `series_list` even when `_target` is absent.
  Frozen totals make the displayed denominator safer, but list mutation should
  still be guarded. If no target exists in tail, the downloader should probably
  consume/log the stale intent and resume current/rest without inserting a
  phantom priority ordering.
- Final success now uses `successful_series >= frozen_total_series`. That is
  reasonable for dedup/requeue safety, but make sure duplicate completed/skipped
  entries cannot falsely count as success. If lists are keyed by series UID and
  deduped, this is fine.

Effect on other parts:

- Download progress UI becomes more stable.
- Any code relying on live `len(series_list)` after yield may observe different
  progress semantics.

## 4. DownloadTask de-dup and count sanity

Files:

- `modules/download_manager/core/models.py`
- mirrored plugin payload copy

What changed:

- Series de-dup now uses `series_uid` when present, else `series_number`.
- Added env gate `AIPACS_DM_DEDUP_BY_NUMBER`.
- Added implausible-count logging `[CriticalCountMismatch]`.

Quality:

Good and covered by tests. This protects task creation from duplicate drag
payloads with missing UIDs.

Effect on other parts:

- Clean tasks are unaffected.
- If a real single study ever contains multiple different series with the same
  `SeriesNumber` and missing `SeriesInstanceUID`, they would collapse. That
  should be rare and invalid-ish DICOM, but it is a theoretical risk.

## 5. DB ownership reassignment guard

Files:

- `database/dicom_db.py`

What changed:

- Added `_DB_ENFORCE_OWNER`.
- `insert_study()` logs `[CrossPatientReassignment]` when a unique study UID
  would move to another patient.
- `insert_series()` logs `[CrossStudyReassignment]` when a unique series UID
  would move to another study.
- With `AIPACS_DB_ENFORCE_OWNER=1`, it blocks owner changes and refreshes
  metadata while preserving the original owner.

Quality:

Good audit improvement. It addresses one of the architecture review's main
concerns.

Limitations:

- Default is observe-only, so it does not prevent bad reassignments unless the
  env var is enabled.
- Logs use numeric foreign keys, not patient IDs/study UIDs on both sides. For
  clinical investigation, the log should include old/new patient IDs or old/new
  study UIDs when possible.
- No targeted tests were seen for enforce/block behavior.

Effect on other parts:

- Observe mode should be low-risk.
- Enforce mode may block legitimate manual corrections or migrations unless
  those flows have an explicit override/correction path.

## 6. Sync manifest, pixel-less DICOM detection, and study state

Files:

- `modules/storage/sync_manifest.py`
- `PacsClient/pacs/patient_tab/utils/utils.py`
- `modules/download_manager/rules/resume_rules.py`
- `modules/download_manager/network/socket_client.py`

What changed:

- `sync_manifest` now has a manifest cache keyed by disk signature and DB facts.
- Pixel-less small DICOM image stubs are detected and, by default, excluded from
  effective disk counts.
- `check_study_complete()` now defaults to `evaluate_sync()` via
  `AIPACS_STUDY_STATE_FROM_MANIFEST=1`.
- DM resume rules reject pixel-less stubs for re-fetch, with an attempt cap.
- Socket download logs pixel-less stubs when small payloads declare image pixels
  but contain no `PixelData`.

Quality:

Good direction. It moves the product toward one disk-first, content-aware truth
model instead of scattered count-only checks.

Risks:

- `AIPACS_SYNC_VERIFY_PIXELS` defaults to `enforce`, so this is a behavior
  change, not just observation.
- `_pixelless_stub_count()` parses small DICOM files. It is bounded, but large
  multi-study opens with many small files could pay extra cost.
- `invalidate_study_state()` exists but is not called anywhere yet. The cache
  relies on directory mtimes plus TTL. That is probably okay for add/remove, but
  explicit invalidation after download/delete/server-grow would be stronger.
- A file overwrite with the same name may not always be represented as clearly
  as an add/remove in the directory signature.

Effect on other parts:

- Table "downloaded" badge, open-skip, and resync should agree more often.
- False-green downloaded states caused by header-only stubs should reduce.
- More studies may be considered partial and re-downloaded if local files are
  detected as unusable.

## 7. Single-click versus double-click download policy

Files:

- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py`

What changed:

- Single-click reconcile/resync no longer enqueues downloads by default.
- Added `AIPACS_SINGLE_CLICK_DOWNLOAD` to restore legacy behavior.
- Added trace markers:
  - `PatientSelectedSingleClick`
  - `ThumbnailPreviewRequested`
  - `PatientOpenDoubleClick`
  - `DownloadEnqueued`
  - skipped enqueue markers

Quality:

Good product boundary. It matches the architecture requirement that
single-click is select/preview and double-click open is the download path.

Effect on other parts:

- Prevents accidental full downloads during browsing.
- If users relied on single-click background downloads, behavior changes unless
  the env flag is enabled.
- Late-discovered DOC or extra studies may be displayed in metadata/thumbnail
  context but not downloaded until open/manual refresh. That is coherent, but UX
  should make it visible.

## 8. Report-status circuit breaker

Files:

- `modules/network/socket_report_status_service.py`

What changed:

- Added circuit breaker for unanswered `GetReportStatus`.
- After repeated failures, calls are skipped for a cooldown to avoid holding the
  shared socket client lock.
- Env-gated with `AIPACS_REPORTSTATUS_BREAKER`.

Quality:

Good. This directly addresses a stress-test bottleneck where report-status calls
blocked patient/thumbnail socket calls.

Effect on other parts:

- Reduces GUI stalls and log spam.
- Report status may remain stale during breaker cooldown, but that is safer than
  blocking the GUI on an endpoint known not to answer.

## 9. Attachment local-first persistence

Files:

- `PacsClient/pacs/patient_tab/utils/patient_sync_service.py`
- `modules/network/upload_download_attchments.py`
- `modules/network/attachment_pending_sync.py`
- `CLAUDE.md`

What changed:

- Reconcile now downloads server-side attachments with `overwrite=False`.
- Local attachment folders are no longer deleted during sync.
- Upload connection failure returns structured failure and marks files pending.
- Added derived statuses:
  - `Synced`
  - `LocalOnly`
  - `PendingSync`
  - `FailedSync` reserved

Quality:

Very good direction. This protects local clinical artifacts from server
availability problems.

Current issue:

- The guard test fails because the literal text `rmtree` appears in a comment.
  Runtime behavior appears correct, but CI fails.

Effect on other parts:

- Server sync becomes non-destructive.
- Attachment UI can show local files even when not yet uploaded.
- Pending manifests become more important for UX and future retry flows.

## 10. Voice notes on multi-study patients

Files:

- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/voice_tool_ui.py`

What changed:

- `_resolve_study_uid()` now prefers `patient_widget.study_uid` before active
  series metadata.

Quality:

This likely fixes the immediate symptom where a recording saved under a
secondary active series study did not appear in the UI that reads the tab's
primary study attachments.

Tradeoff:

- Clinically, a voice note recorded while viewing a secondary study could be
  expected to attach to that secondary study. This change chooses UI visibility
  under the primary tab study instead. That may be correct for current product
  behavior, but it should be treated as an intentional product decision, not a
  general multi-study attachment model.

Effect on other parts:

- Voice notes become visible in the current tab's normal attachment UI.
- Secondary-study-specific attachment association remains unresolved.

## 11. Network and download robustness

Files:

- `modules/download_manager/core/constants.py`
- `modules/download_manager/ui/widget/_dm_workers.py`
- `modules/download_manager/network/grpc_client.py`
- `modules/download_manager/network/socket_client.py`

What changed:

- Added temporary/permanent failure classification.
- Temporary network failures retry up to `MAX_RETRIES_TEMPORARY`.
- User is notified after network failures exhaust their budget.
- Image count normalization now accepts multiple server key names.
- Socket batch size can grow on stable connections.

Quality:

Mostly good and well motivated. The added tests pass.

Risks:

- Failure classification is broad. Unknown errors default to temporary, which
  favors persistence but can retry too much on some permanent server/data bugs.
- Adaptive batch growth should improve stable links, but can increase memory or
  payload size until the shrink path reacts.
- `too large` is classified temporary, which is okay if batch shrink handles it,
  but watch for repeated retry loops.

Effect on other parts:

- Better behavior on weak internet.
- Potentially faster downloads on stable LAN/server.
- More visible user messaging for exhausted network failures.

## 12. Header scan performance

Files:

- `PacsClient/pacs/patient_tab/utils/image_io.py`

What changed:

- Header scan slow-disk detection probes more files and uses a lower threshold.

Quality:

Reasonable performance adjustment. It targets a real issue where early warm
files under-measured cold-disk cost.

Effect on other parts:

- More studies may choose parallel header scanning.
- Should reduce first-open stalls on large/cold studies.
- Slight overhead for the longer probe, but only on eligible series.

## 13. Build, plugin, and CD viewer reliability

Files:

- `builder/release_gate.py`
- `builder/build_release.py`
- `builder/materialize_plugin_packages.py`
- plugin payload mirrors
- `modules/cd_burner/portable_viewer/_hermetic.py`
- `modules/cd_burner/portable_viewer/aipacs_lite_viewer.py`
- `modules/cd_burner/portable_viewer/viewer_app.py`
- `builder/spec/appA_workstation.spec`

What changed:

- Added source-freshness release gate.
- Namespace shadow validators ignore pure data folders.
- Lite viewer enforces frozen hermetic `sys.path`.
- Lite viewer selftest uses `find_spec()` for codecs.
- UPX disabled for clinical build reliability.
- Download-manager plugin payload mirrors were updated with the core DM changes.

Quality:

Good. These changes reduce build-from-stale-source and host-environment failure
modes.

Effect on other parts:

- Builds can fail earlier if the checkout is on a non-release branch or behind
  upstream.
- Installer may be larger because UPX is disabled.
- CD viewer becomes less vulnerable to customer-machine Python/Numpy shadowing.

## 14. Version, config, and generated file changes

Files:

- `main.py`
- `pyproject.toml`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py`
- `builder/spec/appA_version_info.txt`
- `config/servers.json`
- `config/patient_table_sort.json`
- `generated-files/runtime_profile.json`

What changed:

- Version moved to `3.3.2`.
- Release info text changed.
- Server config and patient table sort config changed.
- Runtime profile timestamp changed.

Quality / release hygiene:

- Version bump is expected if this is a release candidate.
- `config/servers.json`, `patient_table_sort.json`, and
  `generated-files/runtime_profile.json` look like local/environment state. They
  should be reviewed carefully before commit. These can accidentally ship local
  server entries, UI sort state, or generated machine-specific data.

## Test Results Observed During Review

Passed:

- `tests/code/download_manager/test_series_dedup_count_guard.py`: 8 passed
- `tests/code/storage/test_sync_manifest.py`
  + `test_sync_mode_policy.py`
  + `test_open_skip_download_when_complete.py`: 27 passed
- `tests/code/download_manager/test_batch_growth.py`
  + `test_image_count_normalization.py`
  + `test_unstable_internet_retry.py`: 29 passed
- `tests/code/cd_burner/test_hermetic_and_shadow.py`: 5 passed
- `tests/code/builder/test_release_parity_guards.py`: 14 passed

Failed:

- `tests/code/download_manager/test_multistudy_identity_guards.py`: 4 failed,
  1 passed. Cause: test helper `_si()` is called with wrong argument shape.
- `tests/code/download_manager/test_download_task_dedup.py`
  + `test_dm_preempt_on_drag.py`: 3 failed, 6 passed. Cause:
  preempt-on-drag stub still defines a two-argument `request_critical_series`
  but production now passes `series_uid=...`.
- `tests/code/network/test_attachment_local_first_persistence.py`
  + `test_report_status_circuit_breaker.py`: 1 failed, 9 passed. Cause:
  source guard sees the literal text `rmtree` in a comment, not a live call.

Not run:

- Full test suite.
- Full GUI/live multi-study workflow.
- Build/release gate end to end.

## Recommended Fix Order

### P0: Before live testing or packaging

1. Honor coordinator rejection.

   - If `request_critical_series()` returns `False`, do not call
     `_on_series_retry()`.
   - Do not write `.critical_intent.json` before validation.

2. Normalize `series_number` on `series_uid` match.

   - Matching UID should route to the task's real series number.

3. Update all coordinator callers.

   - Pass `series_uid` where available.
   - Check return values.
   - Avoid logging "CRITICAL" success when validation rejected.

4. Fix failing tests.

   - Fix `_si()` helper in `test_multistudy_identity_guards.py`.
   - Update `test_dm_preempt_on_drag.py` stub.
   - Update `_dm_contracts.py` protocol.
   - Fix the attachment source guard/comment.

### P1: Before commit

5. Add tests for the bypass itself.

   Required test shape:

   - invalid series request through `request_critical_series_download()`
   - coordinator returns `False`
   - `_on_series_retry()` is not called
   - `.critical_intent.json` is not written

6. Add DB ownership guard tests.

   - observe-only logs reassignment;
   - enforce mode preserves original owner;
   - normal metadata refresh with same owner still updates fields.

7. Add `series_instance_uid` fallback in the viewer canonical resolver.

8. Wire explicit `invalidate_study_state()` calls after download/delete/server-grow
   events, or document why mtime+TTL is sufficient.

### P2: Release hygiene

9. Separate local config/generated changes from clinical code changes.

   Review before committing:

   - `config/servers.json`
   - `config/patient_table_sort.json`
   - `generated-files/runtime_profile.json`

10. Confirm plugin mirror parity after final DM changes.

11. Run a focused live workflow:

   - multi-study patient with duplicate series numbers;
   - secondary-study drag/drop before download;
   - active download plus drag to another study;
   - DOC separate study first open;
   - local attachment save while server offline.

## Overall Quality Assessment

The change set shows good engineering intent. It does not just patch one symptom;
it introduces layered defenses:

- prevent display-key leak at the viewer boundary;
- reject invalid intent at the coordinator boundary;
- freeze progress totals inside the downloader;
- audit DB ownership movement;
- unify study state around the sync manifest.

That is the correct shape for this class of bug.

The weak point is integration completeness. Some old paths still bypass the new
validation or ignore its return value. A defense that can be bypassed by the
primary public API is not yet a defense. The failing tests are useful: they show
where the code/test contracts need to be brought into the new design.

Once the P0 fixes above are done, I would consider this a strong improvement.
Until then, I would keep it out of a release build.
