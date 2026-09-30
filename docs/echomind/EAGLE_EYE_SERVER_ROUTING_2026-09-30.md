# EchoMind on Eagle Eye Server

The owner directed EchoMind reporting and reference workflows to the Eagle Eye
Server edition on Razi. The older PACS HTTP pilot remains historical evidence;
updating Eagle Eye must no longer depend on replacing PACS_Server.exe.

## Contract

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
workflow. Clinical content is not saved by this text endpoint.

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
