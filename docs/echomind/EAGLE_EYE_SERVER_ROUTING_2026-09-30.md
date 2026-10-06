# EchoMind on Eagle Eye Server

The owner directed EchoMind reporting and reference workflows to the Eagle Eye
Server edition on Razi. The older PACS HTTP pilot remains historical evidence;
updating Eagle Eye must no longer depend on replacing PACS_Server.exe.

## Owner routing authority for all future work (2026-09-30)

Company-managed EchoMind, EchoMind Secretary, Assist/research and Eagle Eye
computation must use the authenticated Eagle Eye Server. Clients send user inputs
and bounded workflow/context data. Server-side implementations own system and
workflow prompts, model selection, provider credentials, inference, web research
and upstream calls to GapGPT or company services. Client-direct company inference
and silent fallback after server failure are prohibited for future changes.
Client serialization of context is data transport; company behavioral prompt
instructions must be composed on the server, not inside the client payload.

The sole direct external AI exception requires both the user's own ChatGPT/OpenAI
API credentials and the user's own explicitly defined prompt. This request goes
from the client to the user's chosen API mode and bypasses Eagle Eye. Merely
choosing a provider, supplying a personal key, or reusing a company workflow prompt
does not qualify for that exception. Do not send the personal provider key to
Eagle Eye for this direct mode.

Server responses may contain display text, derived imaging results, or structured
command proposals for Secretary/Eagle Eye workflows. The server plans and reasons;
the client validates and executes the supported command through its existing
local CommandBus or MCP adapter. Preserve tool allowlists, current patient/study
identity, request ownership and existing permission/confirmation requirements.
Return execution outcomes for subsequent server reasoning when needed. Arbitrary
generated Python, shell commands or executable tool names are not a command contract.

Every newly requested feature must follow this boundary. This is the required
architecture, not a claim that every legacy path has already migrated. The current
Secretary migration now routes company route/plan/repair to the paired server
before legacy client prompt/provider branches; see
[the joint Secretary receipt](SECRETARY_SERVER_CONTRACT_2026-09-30.md).
Its independent real transport tests passed; GUI command execution is a separate
pending gate. Dormant legacy prompt builders remain for migration provenance. Earlier
center-direct flows and client transcription also require explicit migration
evidence before declaring all company provider traffic server-only. The earlier
text-only/STT acceptance scope below describes deployed behavior, not a permanent
exception to this owner rule. Assistant context serialization added in this chat
also has a client `reference_policy` instruction; its behavioral policy must move
to server prompt composition in the corresponding migration slice.

This change records the routing authority in AGENTS.md and CLAUDE.md. No runtime
migration, source launch, server update or new network acceptance is claimed.

## Current text-service contract

Registered RAZI_SERVER aliases (including the owner's registered uppercase-C
alias) select `remote_backend`. A prefix alone never authenticates a caller.
The existing Eagle Eye connection settings own URL, server trust, private client
certificate and token. Requests use `/v1/echomind/process` on the same authenticated
TLS listener as model jobs. No PACS login or provider fallback is used.

Client payloads contain initial text and allowlisted workflow context: modality,
selected source template, correction note, section and study profile. Provider
keys, system prompts, model choices, arbitrary URLs, files and source pixels are
rejected. The server owns provider configuration, prompt composition, model
selection, reference calls and research. Each response returns content, usage and
workflow. Requests and responses are now retained in private user_data history;
clinical bodies are never written to general diagnostic logs.

STT retains the shared `VoiceTranscriptionService` before text submission. This
text contract does not claim server audio ingestion or image-upload support.
Workstation command execution remains local; moving report generation does not
move the CommandBus or grant remote desktop control.

Supported text workflows: Report, Turbo, Chat, Radiopaedia Assistant, Textbook
Search, cited Web Search/Medical Consult, Standard, Assist Standard, report/text
translation, ordinary/Turbo Correction, Breast Assistant, template organization
and linked template translation. Template draft storage/reviewer acceptance
remains client-owned; only source text/block metadata is sent for processing.

## Source ownership and provenance

`modules/ai_imaging/eagle_eye_remote/echomind` contains the reviewed headless
EchoMind service imported from the separate PACS Server checkout, with namespace
adaptation and request-local private-directory selection. `migration_manifest.json`
records the imported file hashes; it is import provenance, not a checksum of later
intentional edits. `upstream_manifest.json` retains the original migration record.
The new template adapter is derived from canonical workstation
`modules/EchoMind/reception_templates.py` without its client-routing branches.

Do not refresh this core wholesale from desktop modules: settings, credential
identity and report/template associations are intentionally request-local and
headless. Current long prompt literals are checked against workstation source by
`test_eagle_eye_echomind_core.py`. Changes to canonical prompt authorities require
a reviewed core refresh and renewed parity checks. No shared global user identity
or clinical database may be introduced.

`server.py` owns inbound token/certificate checks. `echomind/hosting.py` validates
fields, owns bounded global/per-client admission, and returns redacted errors.
The private server configuration adds `echomind.config_dir` (absolute path),
`max_requests` (default 4), and `max_requests_per_client` (default 1). The directory
contains administrator-managed `settings.json` and encrypted `centers.json`.
The service account requires read access; these files must never enter Git,
installer defaults, client responses or documentation.

## Acceptance and build handoff

Current deployment: the versioned Developer candidate is active on Razi's
existing paired TLS port 8002. Final local selection: 252 passed; target staging:
94 passed and pip check clean; 495 mirrors match. All 15 real synthetic
Client-to-Razi EchoMind calls passed across 14 workflows. Turbo Correction now
moves desktop modality to the request and reconstructs the server's region gate.
The private provider directory and source/core provenance remain server-local.
See the [Razi checkpoint](../modules/eagle-eye-server-development/docs/ECHOMIND_SERVER_2026-09-30.md)
for source paths, reversible cutover, native graphics delta and pending GUI/model
gates. Its latest receipts supersede intermediate counts below.

The new endpoint guard failed before implementation: missing handler support and
an attempted legacy PACS login. Initial shared transport/service checks passed
64 tests; subsequent core/isolation/prompt checks passed 25 tests. These are code
checks, not deployment, GUI or model acceptance. Final receipts supersede counts.

Before activation, use a fresh versioned source candidate, preserve the prior
source/config, require empty active model queues, verify candidate hashes and run
guards in the target environment. Keep the established port and TLS pairing.
After activation, test synthetic client-to-Razi workflows and server-owned prompt
execution, including citations and the formerly failing Assist Standard and Turbo
Correction paths. Do not retain clinical input/output in test receipts.

Whole-server acceptance also requires actual model execution/edit/result-display
checks. The recorded Breast classifier schema mismatch and Slicer viewer OpenGL
failure remain separate open gates until directly retested. Capabilities or asset
hash equality cannot close them. Build only after Developer acceptance, through
`BUILD.md` and its role-selected Server route, using the verified prepared native
Slicer payload. No installer is claimed by this source change.


## Assist cross-source review and selected-message follow-ups (2026-09-30)

The Assist-only coordinator `viewer_chat/assist_context.py` adds Use as context
on user and reference-answer bubbles and Review with on reference answers.
Review with resubmits the associated original visible user request to Web Search,
Radiopaedia (Assistant), or Textbook (Search), with automatic memory suppressed.
Use request + answer selects the pair without dropping other chosen documents.
The composer bar accepts a source and a new question; ordinary Assist Send also
uses the same context. Explicit selections replace automatic recent memory.
Without selections, the last six eligible visible messages supply bounded memory.

Quoted material is serialized separately from the current request inside the
existing text field. The server continues to own prompts, credentials, research,
and workflow selection. Current edited HTML is converted to plain text; original
questions remain plain visible user messages, avoiding recursively nested history
wrappers. Source labels identify quoted prior answers; the envelope asks the
server to verify them instead of treating them as authoritative instructions.
Selections and memory reset on history clear/session switch. Generation checks
ignore late reference results/errors after a switch. Retry retains the exact
outbound context snapshot. Oversized context is rejected without silent truncation.

Synthetic guards in `test_assist_followup.py` failed before implementation because
the coordinator did not exist. Initial focused verification: 84 passed (exit 0),
including metadata geometry, teardown, remote routes and consultation. A synthetic
Qt preview was rendered and visually inspected. This is not live source GUI
acceptance: the documented test-control ping returned listener unavailable.
Three real synthetic calls were attempted, but the current workstation connection
configuration failed HTTPS-address validation before network submission. No real
server acceptance is claimed and connection settings were preserved.

This Python submodule inherits the existing EchoMind source-tree package, catalog,
configuration family and edition availability; no new product module or flag exists.
Its source and widget mirrors were synchronized with the scoped tool. The shared
`ai_chat_pages.py` mirror is pending: the source includes another workstream's
in-progress reception conflict change and must not be swept into a payload by
this task. The edition staging guard now requires `assist_context.py`; full mirror
and staging acceptance remains pending that shared-file handoff. No candidate
build, install, restart, deployment or version change was performed.

Final focused selection with the package-registry checks: 88 passed, exit 0.
The last full mirror check found 496 pairs and two shared-file drifts: the page
above and remote_backend.py from concurrent private-history work. Those other
workstream payloads were preserved. The scoped widget/coordinator copies match.

## Private case history (2026-09-30 Developer delta)

The server retains a private SQLite transcript at `echomind.history_dir/history.sqlite3`.
The default uses the runtime user_data root; Razi explicitly selects
`D:/Eagle Eye Server/user_data/echomind/remote_history`. Its ACL grants only
Administrators, SYSTEM and the LocalService worker. This archive is separate from
PACS data, Secretary traces and imaging job logs; it does not mutate live dicom.db.

Optional request_id is a canonical UUID; absent IDs are generated by the server.
Optional case_context accepts only bounded study_uid and session_id references.
The authenticated connection supplies owner; callers cannot spoof it or select a
storage path. These references describe client-origin context, not independently
verified PACS patient identity. Missing context remains unassigned. No patient ID
is inferred from report text. Context never enters provider prompt construction.

The GUI captures study/session context before starting its existing ApiWorker.
The remote adapter generates an ID and privately saves request/response to
`user_data/echomind/remote_history/history.sqlite3`, alongside existing conversation
storage in dicom.db. The server returns the same ID; mismatches fail visibly.
Server history records authenticated owner, workflow, state, time and full
request/response. Provider exception details and credentials are excluded.
Duplicate identifiers are rejected with 409 without another provider call.
History reservation failure returns 503 before processing; completion-write
failure reports that processing occurred and prohibits automatic resubmission.
An unfinished running record means completion is unknown, not safe to retry.

Fail-before: the server rejected history fields with 422, and the client lacked
the bound history API. After implementation, 61 focused guards passed locally
and on Razi (an additional context-isolation guard was added afterward). Two
synthetic calls through the actual paired desktop adapter to the running service
passed Report and Web Search, with shared IDs and identical saved responses in
both stores. This is API/storage acceptance, not a live GUI pass. The human was
asked to relaunch the single source client and repeat the case workflow.

The unrelated long-prompt source/core parity guard failed; no prompt literals
were changed by this delta. Whole plugin mirror verification also reports the
pre-existing shared-page drift. Only owned transport/history and the narrow
worker-binding insertion were synced; other in-progress page changes were not
published to Razi. No build/installer parity or whole-server acceptance is claimed.
New base runtime dependency: modules/ai_imaging/eagle_eye_remote/text_history.py
must accompany the existing remote transport in both editions. No heavy model
assets belong in the Standard Client.

Rollback: stop AIPacsEagleEye after idle checks, restore previous hosting.py,
remote_backend.py and shared-page source from
`D:/Eagle Eye Server/backups/history-20260930`, restore server-config.json to
config/server-20260930-echomind.json, then start AIPacsEagleEye. Preserve the
new history data; do not delete clinical records during rollback. The currently
running source GUI has not been restarted automatically. Port 8002 and pairing
are unchanged. No historical requests were reconstructed.
