# Secretary patient workflows and support contract

Scope: patient-bound Education capture/update, reception notes, voice and support
diagnostics. This is a source inspection and implementation contract, not a live
acceptance receipt. Eagle Eye is the canonical name for all spoken aliases.

Owner clarification and source verification: Comment Sync in the open patient's
Report Status popup is the reception-bound comment. Local Note is the user's
private reminder. The comment sync's local cache is staging/retry state, not the
private Note store. `_pw_panels.py` uses the existing shared
`PatientTableWidget._sync_comment_to_server` helper, which posts to the configured
Reception API `/api/pacs/patients/{patient_id}/comment`. Comment-only sync does not
change report status. Initiating the workflow returns a boolean that explicitly
does not guarantee server success; MCP needs the final asynchronous sync result.

## Verified source boundaries

| Request | Existing implementation | Remaining MCP work |
| --- | --- | --- |
| Save this study as an Education case | `ToolbarManager._save_case_of_day_from_patient`, non-modal `CaseOfDayEntryDialog`, `saved` signal, case database and package metadata | Patient-bound prepare/update/save service, typed fields, background capture/persistence and actual save receipt |
| Sync a patient comment to reception | Viewport Report Status comment uses `_pending_report_comment`, PatientWidget's shared comment cache and existing REST comment sync; private reminder Note is a separate local store | Expose the existing Comment Sync workflow with patient binding and actual server receipt; never substitute local Note or clinical report delivery |
| Record my voice for this study | Inline `VoiceWidget` start/pause/stop and background atomic WAV writing | Explicit start/pause/resume/stop actions, microphone ownership, study binding and completion receipts |
| Send recorded voice | Study attachment upload and pending-sync infrastructure exist. Inline toolbar `_on_mic_send` only stops/saves; default VoiceWidget construction has no sync callback | Select a completed recording by opaque handle; separate upload from reception delivery; authoritative admission linkage and acknowledged delivery receipt |
| Explain slowness | Shared asynchronous `diagnose_resources` action and status polling | Bounded sanitized log evidence, download/viewer status evidence, authenticated Eagle Eye diagnostic analysis and plain-language presentation |
| File a company ticket | No ticket destination supplied in this task | Prepare a report; implement submission only after destination/authentication contract is supplied. Reference numbers require an actual server receipt |

The Education toolbar export currently traverses/copies local DICOM before showing
the non-modal dialog; its save path also performs database/sidecar work inline.
Exposing these callbacks directly as MCP save actions would preserve blocking GUI
I/O. Extract worker-owned services before exposing unattended saving. Existing
capture controls, case events and local Education semantics must be retained.

## Required shared actions (proposed, not registered)

- `prepare_education_case`, `update_education_case`, `save_education_case`,
  `education_case_status`: return a case-session handle, bounded allowed fields,
  selected-study binding and actual persistence status. Updating an existing case
  needs its case ID and revision; it must not silently create a duplicate.
- `prepare_patient_comment`, `sync_patient_comment`, `patient_comment_status`:
  use the existing Report Status / Comment Sync workflow. A comment-only sync
  preserves report status. Keep private local Note actions separate. A send
  timeout becomes unknown/pending, never success; retry semantics must follow
  the existing endpoint contract rather than assume idempotency support.
- `start_patient_voice`, `pause_patient_voice`, `resume_patient_voice`,
  `stop_patient_voice`, `patient_voice_status`, `send_patient_voice`: explicit
  operations rather than a state-dependent toggle. Saved and delivered are separate
  terminal states. Never transmit an unfinished or failed WAV file.
- `collect_support_diagnostics`, `analyze_support_diagnostics`,
  `prepare_support_ticket`, `support_operation_status`: asynchronous evidence and
  local status handles; future submission requires a separate real transport.

Every patient write captures study/admission identity at preparation and rechecks
it before execution. Tab switches invalidate the pending action unless the user
explicitly targets its original study. Names alone cannot establish identity.
Reject stale handles, arbitrary paths, arbitrary generated code and unsupported
fields. CommandBus permissions/confirmation remain client-owned; company planning
and analysis remain authenticated Eagle Eye Server-owned.

## UI and result contract

Show the target study locally, requested operation, editable user-provided content
and progress. Do not overwrite unspecified case fields. Use structured receipts
for draft, awaiting confirmation, recording, saving, saved, uploading, delivered,
failed, cancelled and unknown. Opening a dialog is not saving or delivering.

Secretary responses should explain the practical finding and next step in ordinary
language. Stack traces, source paths and engineering terminology belong in private
support evidence, not the patient-facing conversation. Examples: "The computer's
memory is under pressure" or "The download has stalled; the cause is not confirmed."
Do not claim a company ticket was sent or invent a reference number.

## Diagnostic evidence boundary

The worker samples system CPU, process CPU/RSS, RAM and the application storage
drive. Process CPU uses psutil's 100-percent-per-logical-processor scale and may
exceed 100; it is not the system percentage. A 0.25-second observation is a sample,
not proof of sustained overload or a viewer/download defect.

Future log collection must use fixed application-owned User Data log roots,
bounded byte/time windows, current-session correlation and structured categories.
Allowlisted metadata/status reads from Patient Data must never become arbitrary
file browsing, deletion or raw DICOM upload. Prefer structured error codes and
aggregate counts over free-text redaction alone. Strip patient identifiers,
credentials, paths, prompt/report content and images before external support
analysis. Native crash evidence must follow the current session-scoped log guide.
Keep local evidence separate from the sanitized Eagle Eye request. Do not introduce
a direct provider fallback or a pretend diagnostic endpoint.

## Source receipt for resource sampling

`PacsClient/utils/assistant_settings_service.py` now includes system CPU, process
CPU/RSS, bounded pressure observations and explicit unconfirmed-cause/no-ticket
status in the existing worker/polling action. It does not read patient files,
upload logs, delete data or submit tickets.

Fail-before: the synthetic resource guard failed on the missing CPU field (one
failure, seven passes). After implementation: 26 settings worker/control/navigation
tests passed with exit code 0 and six existing SWIG deprecation warnings. The
service is base application code, not an EchoMind plugin mirror.

Live source acceptance remains pending: documented local Test Control ping is
unavailable. Human source launch/login under the existing testing contract is
required; automated tests do not constitute GUI acceptance. No patient actions,
voice recording, reception sends, server deployment or tickets were executed.

This extends the Secretary control work under OPT-23; performance findings remain
with their existing subsystem owners. Implementations of the proposed actions
above remain outstanding.

The detailed function/error/UI/log/Windows Application coverage review is in
[Secretary error observability review](SECRETARY_ERROR_OBSERVABILITY_REVIEW_2026-10-01.md).
Its proposed production actions are not yet registered or implemented.
