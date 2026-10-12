# Shared Windows AI connection and speech exception

## Existing behavior

AI Connection already hosts the original Settings owners and saves one Eagle Eye
profile (URL/IP and port, device token file, pinned CA and optional client TLS pair).
Imaging, EchoMind remote transport, Secretary planner and CRM use the central
`eagle_eye_remote.Client`; opaque human sessions and per-request server grants are
preserved. No new login UI, provider selector, second listener or active-service
transition is introduced. Native GUI acceptance remains pending.

VoiceTranscriptionService already implements automatic Google Speech, GapGPT
Whisper (`aipacs_3`), company service 1 then company service 2, with 45-second
per-attempt budgets and short-circuit on a useful transcript. Manual provider
selection remains authoritative. Both chat and Secretary use this shared service.
These speech uploads are the owner-approved exception to company inference routing;
the new server speech endpoint is owned by the server workstream and is not a
required Windows migration in this slice.

## Scoped corrections

- Shared connection test now checks compatible device capabilities AND exchanges
  or validates the current ordinary human session before success. It returns only
  a boolean and resolved authority label, never session/password/principal values.
  UI states that module grants are checked per request and this is not model
  readiness certification. All work remains in the existing settings worker.
- Company route selection no longer depends on a special Razi test-center key.
  All company selections use Eagle Eye. Public legacy company sender names are
  rebound to the server-owned surface; retired arbitrary-key/image calls fail
  closed with actionable messages. Pure report/geometry builders remain local.
  Low-level llm_client refuses direct company credential resolution/inference.
- EchoMind UI uses a memory-only ordinary-login readiness hint, not a dummy key
  or client-side module approval. The server remains the admission/grant authority.
  Turbo and Turbo correction remain server-owned when Send is in personal mode;
  the retired local Turbo prompt/provider fallback has been removed from its worker.
- Personal API transport requires the user's configured key/endpoint and an
  explicit saved workflow prompt before transport. Its system message is the
  user-defined prompt only; company system prompts and transient center-key
  overrides are not forwarded. Secretary already enforces its own personal prompt.
  Existing feature prompt fields remain the UI; no additional credential form.
- Blank/invalid STT provider normalization selects Auto. Auto's connection test
  walks the same priority instead of reporting a nonexistent URL. Its check
  proves prerequisites/reachability only, not actual transcription. The settings
  help explains the order and that manual choices do not auto-fallback.

## Verification and limits

The scoped combined suite passed 112 tests (exit 0), covering shared probe human
admission, all-center route selection, direct-company refusal, server-bound public
senders, personal prompt/key boundary, Auto probe/order, settings worker and
session/IPC guards. Mirrors: 528 pairs match after seven EchoMind sync updates.
Pre-edit candidate guard results and exact paths/hashes are recorded in the final
private source receipt. No installed app was opened, no login automated and no
Razi executing source changed. Complete union source parity and GUI acceptance
remain owned by final inactive reconciliation. No build/release or full payload
parity is claimed. Android is a separate owner; iOS source/access is unavailable
in this Windows task and no iOS implementation pass is claimed.

This is not a claim that every historical private helper has been migrated into
a server workflow. Unsupported legacy arbitrary-key/image entry points fail
closed; any additional caller requiring a dedicated server action must be mapped
explicitly rather than re-enabling a direct provider path. Existing company server
prompts/models/grants and server-hosted snapshot code were not edited here.
