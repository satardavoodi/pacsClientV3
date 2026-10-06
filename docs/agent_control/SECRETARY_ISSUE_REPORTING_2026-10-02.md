# Secretary workstation issue reporting

Status (2026-10-04): source fixes and automated checks passed. Eagle Eye Help Ticket intent and website transport are deployed. The previously consented pending ticket was received by the website. Fresh source GUI and installed-package acceptance remain pending.

Canonical cross-project contract:
`D:/laragon-www/workspace-docs/08-workstation-support-issues.md`.
Receiver/operations receipt: Laravel `docs/PACS_ISSUES.md`.

## Source behavior

Secretary has a `Report an issue` button and typed `open_support_issue` action.
The action accepts only an optional description of at most 4000 characters,
opens the same local editable form, and never sends automatically. Its server
catalog tells the planner to use the user's transcribed description without
invented incident details. Existing orb transcription remains on the shared
VoiceTranscriptionService; no new recorder, AI provider or prompt route is added.
`support_issue_status` returns safe form state/receipt only, never the description
or diagnostics. UI actions are advertised only when Home is present. The Test
Control `support_control` wrapper uses assistant mode for opening and read-only
mode for status; its session recorder omits description entities.

The form captures user/category/incident time/selected connection/app version,
offers optional Windows evidence, and requires local review/consent before Send.
It rechecks the PACS user/connection before a new send. Previous encrypted
pending content is restored locally, remains immutable for retry, and can be
discarded through a local confirmation. Retries recheck the PACS user and reject
another website credential/destination rather than rebinding old content.

IssueReporter uses the existing AipacsWebClient public request path and identity
lookup on a worker. The client adds an opaque credential binding and optional
redirect policy; unrelated calls preserve their previous request arguments.
Support requires HTTPS except loopback and disables HTTP redirect following.
The outbox uses native user-bound Windows DPAPI through stdlib ctypes, exclusive
temporary creation, fsync and replacement; no new pywin32 runtime dependency,
plaintext fallback or adjacent encryption key is introduced. One pending payload
is allowed per account; seven-day expiry is enforced on open/retry and cleanup
is lazy. Errors return fixed codes, not exception text or credentials.

Diagnostic collection uses the four existing fixed 64-KiB tails, safe exception
counts and repository-verified stack locations. It adds at most three exclusive
native-fault log tails from the last seven days by mtime, with safe fault counts
and stack locations; no raw filenames/messages or legacy shared trace is sent.
Optional Windows projection remains product-basename attributed. Coverage gaps
are retained, not presented as healthy state or an established root cause.
Source locations absent from the current project root are omitted, including
unavailable installed-source locations. No patient database/data, images, reports,
conversation memory, audio, dumps or arbitrary file paths are collected.

OperationStore runs disk, identity/token lookup, collection and HTTP on plain
worker threads. Qt only captures scalars, renders the form and polls completion;
workers do not access widgets. Close never joins a worker or destroys a running
QThread. Received requires a matching client UUID and website issue UUID; unknown
delivery stays pending. The displayed issue identifier is never invented locally.

## Evidence

Before implementation, the new Python guard failed at collection because the
module did not exist; Laravel had four missing-route failures. A later focused
guard failed before correcting headless advertisement of the local UI action.
Final focused Python and owned builder selection is recorded in the validation
summary below. PHP selection: 28 tests / 190 assertions, exit 0.

Owned EchoMind/Identity mirrors were synchronized through scoped
`sync_plugin_mirrors.add_paths`, including catalog/docs. Two dedicated builder
guards verify eight owned mirrored files and three changed server snapshot
hashes. The global verifier checks 504 Python pairs and still reports one
pre-existing `modules/EchoMind/viewer_chat/ai_chat_pages.py` mismatch. It was not
synchronized by this slice. No global mirror, release, installer or lint pass is
claimed; Ruff remains unavailable under the existing repository baseline.

Synthetic Qt rendering at 480 x 640 and synthetic rendered Laravel inbox/detail
HTML were visually inspected. The Qt preview needed an explicitly loaded Segoe
UI font for the offscreen host; live application font behavior was not changed.
Preview: `generated-files/support-issue-form.png`. These are layout previews,
separate from mandatory source workflow acceptance.

Read-only documented Test Control probes returned ping=true and an action list.
The current source process does not contain `open_support_issue` or
`support_issue_status`; it predates this change. No hot reload, source restart,
login, clinical interruption or real support upload was performed. A human
fresh source launch/sign-in was requested through the existing testing protocol.
The running listener's presence does not imply this feature was tested live.

## Acceptance and rollback

After a human-controlled fresh source launch/sign-in outside clinical work,
probe ping/list_actions. Click the real Report an issue button; verify identity,
connection, incident time, consent gating and scroll/keyboard accessibility.
Use a synthetic account paired to an isolated loopback Laravel test receiver,
not an ad-hoc production submission or a replaced live account/config. Check the
matching received UUID in both form and Super Admin; verify safe diagnostics,
status changes, a frozen retry after a synthetic dropped response, account and
connection changes, and rejected/expired outbox handling. Voice acceptance needs
the matched deployed server catalog and shared STT result; opening must not be
reported as receipt. Never restart active recording or clinical work to do this.

Rollback is limited to the new support form/reporter/tests and additive issue
action/UI/client-request changes, their owned mirrors and matching server assets.
Restore prior shared files by exact hunks, preserving concurrent Secretary,
selection/media, voice, identity, viewer and website changes. Local pending DPAPI
files and server evidence are user data, not disposable build output. No version,
commit, push, release build, production credential edit or cleanup was performed.

Owned seams: support_issue_dialog.py, support_issue_reporting.py,
support_diagnostics.py source-frame projection; Secretary orb button, support
adapter/factory/envelopes/permissions/client+server validators/catalogs;
Identity AipacsWebClient; Test Control support wrapper and recorder; three
changed server snapshot hashes; scoped mirrors and new synthetic/builder guards.

## Validation summary

The final direct Python selection passed 110 tests with one host-restricted
symlink test skipped and six existing SWIG warnings (process exit code 0).
It covered issue reporting, existing diagnostics, Secretary capability alignment,
Identity web requests, Secretary server/MCP entrypoints and owned payload parity.
The Laravel issue and Super Admin access/privacy selection passed 28 tests with
190 assertions (process exit code 0). Scoped Pint checks passed for six new PHP
files. Synthetic Qt and Laravel previews were inspected; these are not live
source-app or deployed website acceptance.

The global mirror verifier retained one pre-existing mismatch in
`modules/EchoMind/viewer_chat/ai_chat_pages.py`; all eight owned issue payload
pairs and the three changed server snapshot hashes passed their focused guards.
The existing Test Control listener answered ping, but its running source process
did not expose the new issue actions. Live acceptance remains pending a human
fresh source launch and sign-in, followed by matched website/server publication.

## Consented raw log archive continuation

Owner requested a ZIP of recent user_data logs. The form now offers a separate,
off-by-default raw ZIP checkbox with sensitive-content notice. The worker builds
an in-memory ZIP from nonrecursive log/text files and numbered rotations in the
configured LOGS_DIR; no arbitrary path action or Secretary auto-send was added.
Timestamped records are filtered to 24 hours before submission in workstation
local time. Untimed files are selected by recent modification time and may contain
older records. The manifest records source, selection and truncation. Caps: 32
files, 2 MiB tail per file, 8 MiB total reads, 2 MiB compressed. Oversize creation
fails; there is no silent omission. Failed requests preserve the same ZIP in the
existing DPAPI outbox; archive transfers use a 90-second request timeout.

Website receiver requires support-raw-logs-v2, verifies SHA-256 and bounded ZIP
structure/CRC/member names without extracting files, and stores the archive in an
encrypted nullable longText field. Super Admin download is private, no-store,
attachment-only and audited; expiry and purge include the ZIP. Raw log privacy
cannot be equated with the earlier safe-projection contract. User consent is
required; no raw clinical log was read/uploaded during development or testing.

Focused source verification: 27 passed, one host symlink skip, six existing SWIG
warnings. Laravel local/private Hostinger: 31 tests, 220 assertions. Production
receiver published and eight hashes/new archive column verified; an actual
Python-generated synthetic ZIP passed the live validator. No real ticket was
submitted. Fresh source GUI upload and installer verification remain pending.
A separate builder parity guard found pre-existing/concurrent bus_factory.py
source/payload drift; it was not synced as part of this slice.

## Voice description continuation

The issue form includes a microphone icon and Speak issue / Stop and transcribe
control. A worker records at most 120 seconds and calls the existing
VoiceTranscriptionService using current EchoMind Voice-to-Text settings. Recording,
temporary WAV creation, transcription and cleanup remain outside the GUI thread.
The recording is not an issue attachment. Transcribed text is editable; sending
still requires review, consent and Send issue. Existing description text is retained.
Closing cancels the take; account/connection changes discard stale results. An
already running transcription request may finish before its result is discarded.

Direct focused verification passed 24 tests with six existing SWIG warnings,
covering voice, issue submission and log ZIP behavior. Voice tests use synthetic
audio and a fake service; no microphone or provider request was performed. The
synthetic Qt preview was inspected. Real microphone/transcription and source GUI
acceptance remain pending a human fresh source launch and sign-in. The website
already accepts description text, so this change requires no receiver deployment.


## Local Help Ticket packages (2026-10-03)

Submission workers retain `user_data/help-ticket/YYYY-MM-DD_HH-MM-SS_<client_issue_id>/ticket.zip`.
The ZIP contains the frozen website request, description, diagnostic projection, consent-selected raw log ZIP,
and up to ten local WAV recordings. `receipt.json` records pending or received delivery and is updated on retry.
Packages survive successful delivery and pending-outbox expiry/discard; no automatic archive deletion is introduced.
Audio stays local and is not added to the website payload. Secretary Help Ticket dictation and issue-form dictation
retain accepted recordings in the draft until submission. Cancelled, failed or stale-account takes are discarded.
Existing visible drafts are preserved. Package I/O remains worker-owned. Local packages are ordinary ZIP files;
the separate retry outbox retains its existing DPAPI protection. No credentials are added to archive metadata.
Focused automated verification: 32 tests passed. Native GUI acceptance remains pending because the documented
local test-control socket is unavailable; no website ticket was created for testing.
# Retry and Secretary feedback investigation أ¢â‚¬â€‌ 2026-10-04

The website package-v3 receiver is published (see the website deployment record
`D:/laragon-www/deploy-record-website-support-package-2026-10-04.md`). This does
not establish delivery of an actual pending ticket.

Read-only checks of the latest pending attempt found no matching website receipt.
Its local receipt remains `pending`, `DELIVERY_UNCONFIRMED`, with no HTTP status
and failure stage `transport_or_receipt`. The paired website account passed an
authenticated read. No real ticket, voice or diagnostic archive was resent during
this investigation.

Synthetic unauthenticated JSON transport checks from the workstation returned
401 for a 1 KiB body, but a roughly 2.6 MB random-base64 body failed with
ConnectionError after 15.4 seconds. A roughly 2.6 MB synthetic request from the
Hostinger host returned 401 normally. This reproduces a workstation-to-site
large-upload transport problem; it does not identify the responsible network
component or prove the precise exception from the previous attempt.

Two independent client control/feedback gaps are confirmed in source:

- `submit_help_ticket` checks only the form's Send button. A restored pending
  request disables Send and enables Retry after local review; the adapter never
  selects Retry, so a spoken retry cannot execute this path through that action.
- The issue dialog stores terminal `public_result` and displays its own status,
  but emits no completion notification to Secretary. `_open_help_ticket` announces
  draft readiness and ends the Secretary cycle without observing submission.

The server Help Ticket prompt explicitly produces drafts only and forbids sending;
its response schema carries category and description, with no retry operation.
Consequently asking to resend in Help Ticket mode still enters draft preparation.

Required follow-up: preserve server-owned intent classification and local consent,
provide a typed pending-ticket retry path, bind safe running/received/pending
events to the initiating Secretary conversation, and diagnose large-upload
transport without substituting a fake success. Only a validated website receipt
may display Done/sent. These follow-ups are diagnosed, not implemented or GUI-verified
by this read-only investigation.


## Implemented retry and receipt correction â€” 2026-10-04

This implementation supersedes the read-only investigation above. Eagle Eye's dedicated prompt classifies prepare/retry/status and negotiates the operation through support_ticket_intents=1; legacy clients retain the draft shape. Razi's isolated revision passed 41 server/runtime guards, pip check and authenticated synthetic LLM acceptance for all three intents. No generated executable plan is permitted in Help Ticket mode.

The local typed submit action selects Retry for restored pending content, requiring the same local review and consent. Dialog deliveryChanged events update the initiating Secretary response and status. One observer prevents main/popup duplicate messages; progress updates do not flood the conversation or overwrite unrelated active work. Done requires a verified website receipt. A separate identity/URL-bound DPAPI receipt index retains the safe outcome for 90 days; restart retry/status can report an already received ticket rather than pretending another send occurred.

Large approved JSON uses 49,152-byte paired encrypted chunks and final full-payload SHA256 validation through the existing package-v3 receiver. Interrupted parts remain idempotent and finalization requires every matching part. HTTP/auth/rejection errors never reroute. A transport-only failure may use the authenticated site's public origin capability, restricted to ai-pacs.com support writes; original URL, Host, SNI and certificate verification stay intact. Configured proxies, custom/disabled TLS verification, private/non-IPv4 addresses and unrelated API paths are refused. Server public origin configuration is owner-controlled; no DNS, proxy rules or company AI routes changed.

Evidence: from this computer a synthetic full chunk failed on the Cloudflare path and reached the same website's validated HTTPS origin in under one second. The new paired capability and invalid full-size chunk probe reached 422 without creating an issue. The owner-requested resend then transferred all 63 parts of the existing immutable approved ticket in approximately 70 seconds, received a matching client_issue_id and valid issue UUID, cleared the pending outbox, and saved its DPAPI history and local archive receipt. This was the legitimate previously requested delivery, not a synthetic issue submission.

Website local and private Hostinger suite: 17 tests / 131 assertions. Workstation focused suite: 156 passed, one host symlink skip; compact UI and support delivery suite: 42 passed. Reopening an already received ticket status retains Done rather than reverting to Confirmation required; its guard failed before the correction. Scoped mirrors include the new Identity transport helper. Global parity has one unrelated pre-existing viewer_chat/ai_chat_pages.py drift, preserved. Fresh native GUI acceptance remains unverified: documented control ping cannot reach the Test Server, and no app was started/restarted or logged in by automation. No executable release is claimed.

Deployment records: docs/agent_control/deploy-record-secretary-help-ticket-2026-10-04.md; D:/laragon-www/deploy-record-website-support-retry-2026-10-04.md; D:/laragon-www/deploy-record-website-support-origin-2026-10-04.md.
