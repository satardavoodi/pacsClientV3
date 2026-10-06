# Secretary support and patient communication source implementation

Status: source implemented, automated verification recorded below; live GUI and
server deployment pending. This receipt supersedes the proposed-only status for
the actions listed here in the earlier observability/patient-support reviews.
It does not mark the overall Secretary workstream complete.

## Shared action surface

Four support actions, three Comment Sync actions and seven voice actions are
registered in the production CommandBus factory. Mobile MCP enumerates the same
registry. Strict schemas and explicit side-effect classification are shared;
client and server planner validators/catalogs recognize the new actions.

- Support: collect_support_diagnostics, support_operation_status,
  get_visible_app_errors, get_recent_function_results.
- Reception comment: prepare_patient_comment, sync_patient_comment,
  patient_comment_status. Preparation pins the active tab/study/patient identity;
  send rechecks it and requires confirmation. Uses the existing shared comment
  cache and REST Comment Sync helper on a worker. Keeps report status and private
  Note unchanged. One send runs at a time; repeat invocation of the same draft
  returns its existing operation. Network failure is an unknown delivery outcome.
- Voice: prepare_patient_voice, start_patient_voice, pause_patient_voice,
  resume_patient_voice, stop_patient_voice, patient_voice_status,
  send_patient_voice. Preparation creates an app-owned study folder on a worker;
  start uses that prepared path in the existing inline recorder without mkdir.
  Explicit pause/resume avoids blind toggles. Saved requires the actual WAV-write
  signal. Upload uses the existing study attachment transport, narrowed to one
  completed take by selected_files. Legacy full-study sync remains the default.

The testing MCP exposes support_control, patient_communication_control and
offline_support_diagnostics. Offline evidence collection operates outside Qt and
does not require app IPC; it reads source-runtime log roots, not every installed
profile. The generic command recorder omits comment/voice preparation entities.

## Evidence and privacy behavior

Log collection reads at most 64 KiB from each of four fixed files under LOGS_DIR:
app, viewer, download and database diagnostics. It returns severity counts and
allowlisted exception-type counts, never raw text or paths. Tail samples are not
precise time windows and cannot establish a root cause.

Windows collection is a fixed local Application query for the last 24 hours,
bounded to 1000 candidate events and 100 output events, with a 15-second subprocess
deadline. Structured AppName must match AIPacs.exe; unrelated applications and
generic source Python events are excluded. Results retain safe time/event/code
fields only. Basename attribution remains a product candidate, not verified
session identity or proof of a source crash. No-match/access-denied/unavailable/
timeout states are distinct. WER/raw message/dump upload is not implemented.

Visible error inspection returns warning/critical severities of Qt message boxes,
not their patient-sensitive text. Recent function receipts retain only a bounded
100-item in-memory safe projection; they record immediate function results,
while background work requires the owning status action.

## Verification

Initial synthetic support guards: four failures before implementation.
Final automated selection: 255 passed, one host-restricted symlink test skipped,
nine existing TLS/SWIG warnings; direct pytest exit 0. Coverage includes strict
arguments/permissions, patient switch rejection, confirmation, actual comment
acknowledgment, safe failure output, off-GUI comment writes, repeat-send identity,
voice state/receipt semantics, one-take selection, bounded evidence, Windows
failure states, existing voice/attachment retry guards, SDK inventory, Gateway
and settings. All data and transports in these guards are synthetic.

Owned EchoMind mirrors were synchronized through scoped add_paths. The global
mirror verifier checks 502 pairs and still reports the pre-existing unrelated
viewer_chat/ai_chat_pages.py drift. That file was not synchronized by this slice.
The server snapshot manifest hashes owned catalog/validator changes; this is not
a deployment receipt. No build, commit, push, real comment send, recording,
attachment upload, cleanup, Windows-event export or clinical test was performed.

Documented local Test Control ping remains unavailable. Source launch/login and
affected-workflow GUI acceptance remain required under the repository agreement.

## Outstanding work

- Automatic transcription-to-comment extraction/review/send orchestration.
  Existing transcribe_voice still opens the report transcription workflow; the
  user-reviewed transcript can be supplied as comment text. Do not add a new
  legacy company-direct transcription route.
- Authoritative reception delivery for voice. PACS upload explicitly returns
  reception_delivery_confirmed=false; do not tell the user reception received it.
- Education case prepare/update/save services and background persistence;
  existing navigation actions are not a completed save contract.
- Rich app-owned error categories, native current-session evidence, exact
  executable-path Windows attribution and authenticated Eagle Eye diagnostic
  analysis. Existing projections do not perform root-cause diagnosis.
- Ticket submission requires the future company endpoint and actual receipt.
- Full source UI, deployed server catalog and installer acceptance.

Owned source seams: PacsClient/utils/support_diagnostics.py; Secretary support,
patient_communication and patient_voice adapters; factory, envelopes, permissions,
validators and catalogs; voice_tool_ui.py prepared-path branch; attachment uploader
selected_files branch; testing MCP wrappers. Bounded pre-edit voice/uploader
backups are outside the checkout under the task-specific temporary backup folder.
Rollback must remove only these changes while preserving concurrent edits.

## October 2 issue-reporting continuation

The former future-ticket-endpoint gap now has a local source implementation:
paired Laravel receipt, private Super Admin inbox and diagnostic download, a
user-reviewed Secretary form, safe source/native stack projections and a DPAPI
retry outbox. Production website/server catalog, fresh source GUI and installed
acceptance remain pending. See
[the issue-reporting receipt](SECRETARY_ISSUE_REPORTING_2026-10-02.md).
