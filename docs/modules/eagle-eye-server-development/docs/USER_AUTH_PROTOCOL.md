# Human authentication and Eagle Eye grants

## Superseding connection contract - 2026-10-12

[Canonical connection boundaries](../../../architecture/EAGLE_EYE_CONNECTION_BOUNDARIES_2026-10-12.md) supersedes historical pairing/TLS prerequisites in this document. Ordinary Eagle Eye ingress uses HTTP IP:port and username/password. The server verifies PACS first, tries Reception only on credential rejection (401), then independently enforces internal feature/module grants. Caller-provided PACS/provider tokens and device pairing are not required. A server-issued opaque password-login session is an implementation detail.

QR/device pairing and HTTPS are reserved for mobile Android/iOS remote Agent PACS to Windows DICOM Client. Windows uses native Secretary; mobile has no imaging AI feature. Optional legacy TLS and provider-token code remain implementation compatibility, not prerequisites under this contract. Documentation does not activate a source change or certify unresolved client login/CRM identity gaps; see the canonical audit.


Owner contract: 2026-10-09. This supersedes proposals allowing Eagle Eye-only
accounts to authenticate remote Windows/mobile AI requests. Only PACS or Reception
can attest remote human identity; the local console administrator manages grants.

Status: coordinated source implementation in progress; not activated on Razi.

Owner correction (2026-10-09): client login screens and ordinary login behavior
remain unchanged. No PACS/Reception selector or separate Eagle Eye sign-in is
part of the contract. On the first protected request the client exchanges the
current logged-in user's credentials automatically, in memory only. The server
tries configured PACS first, then Reception only after credential rejection.
An accepted PACS identity with denied Eagle Eye grants must not fall through to
Reception. Temporary authority outages return an availability error.

Windows and Android ordinary login paths are restored; automatic credential
exchange is implemented. Earlier Reception-specific entry/workspace UI is
superseded and removed. Local combined identity/CRM/IPC/startup verification
passes 163 tests. Android passes 294 JVM tests and ten routing/report guards;
its debug APK is built and installed on the emulator. Live acceptance and source
parity remain separate gates.
iOS source access and live GUI acceptance remain pending.

Resident Slicer obtains only the opaque Eagle Eye session through the existing
authenticated private parent channel. Parent generation is checked before response
consumption. Local invalidation schedules bounded background logout through the
original pinned transport. Passwords and PACS tokens do not cross this channel.

## Shared AI connection and speech exception — 2026-10-09

AI connection Settings identifies one reviewed Eagle Eye Server address and port
with its existing pairing/TLS trust. Company Eagle Eye imaging, EchoMind,
Secretary and CRM reuse that same connection and human admission. A successful
connection check establishes transport readiness, not user/module permission.
Every protected request still requires upstream identity plus local grants.
Changing server, pairing, account or profile invalidates cached human admission;
requests must not reuse another profile's session or silently fall back to a
company provider from the client.

The AI backend choice is AI-PACS via Eagle Eye Server or the existing personal
API mode. Personal direct inference requires the user's own credentials and an
explicitly user-defined prompt; personal credentials are not sent to Eagle Eye.
A personal text provider cannot substitute for unavailable image-analysis models
or grant CRM access. Keep existing login screens and workflow permissions.

Voice to Text has a separate owner-approved routing rule: the default is Auto,
with Google Speech first, GapGPT Whisper second, then company transcription
services. Preserve explicit saved speech choices. Windows callers use the shared
VoiceTranscriptionService. This speech fallback is not inference fallback for
EchoMind reporting, Secretary planning or Eagle Eye analysis. Speech results
enter the selected AI route as text; transcripts and audio remain sensitive.
Android shared AI/Auto speech implementation passes 306 JVM tests and twelve
routing/report guards; debug APK build and emulator installation passed. Human
GUI and live provider acceptance remain pending. Do not infer iOS compliance
from Android or Windows tests.

## Mobile speech continuation contract

`POST /v1/speech/transcribe` uses the same paired listener and human session.
JSON fields are exactly `protocol: 1`, UUID `request_id`, `feature` (`echomind`,
`secretary` or `crm`), `audio_base64`, `format` (`wav`, `m4a`, `mp3`) and
`quality_mode` (`clear`, `noisy`). Raw audio is at most 8 MiB; JSON at most 12 MiB.
The named feature grant and Server license are mandatory before upstream work.
The server owns provider origins and credentials; client URLs/keys are rejected.
Two bounded concurrent requests try GapGPT Whisper, Company 1, then Company 2,
with a 45-second read budget per provider. Client speech read timeout must allow
180 seconds; an interrupted request must not automatically replay audio.
A transcript with `accepted: false` is a quality result, not a routing failure.

Success returns `ok`, `transcript`, `accepted`, `route_used` and redacted
`attempts` (`provider`, `ok`). No audio, key, private path or raw upstream error
is returned or retained. 401/403 are authentication/permission failures; 429 is
busy; 503 means missing speech configuration/credentials or exhausted providers.
Speech is advertised in `/v1/capabilities` only when EchoMind server configuration
exists. Capability discovery does not prove credentials or live provider readiness.

The client Google stage remains separate: Android's existing Google recognizer
is live-microphone only. Recorded-file Auto must explicitly record that stage as
unavailable until a recorded-audio recognizer is implemented, then use this
server continuation. Do not claim prerecorded Google coverage from a skipped
stage or a synthetic test. iOS requires a separate implementation receipt.

## Single Send reporting — 2026-10-09

Windows/mobile report authoring exposes one Send action; the client submits a
normal report request with modality, selected template and study profile. It does
not choose Turbo or issue a second company request. Company report client read
timeout is 480 seconds to allow both bounded upstream attempts; timeout must not
replay the report. Eagle Eye invokes the existing
Turbo/ChatGPT reporter and server-owned prompt first. On upstream exception,
timeout or empty/error-only content, it invokes the native company report service
once. Authentication, user grants, license and request history admission happen
before either upstream call. A local denial never triggers provider fallback.

Success includes redacted `route_used` (`turbo` or `company_service`) and
`fallback_used`. Both attempts share one request/history identity and token
accounting context. If both fail, return an error rather than an empty success.
Personal direct API retains the user's own credentials/prompt and never enters
this company fallback. Legacy `workflow=turbo` is a compatibility alias for the
same server policy; it is not a client selection control.

Report attachments remain supported by Turbo. The native fallback does not have
an attachment contract, so a failed attached report returns an explicit error;
attachments must never be silently dropped or described as analyzed. Translation,
Correction and other workflows do not acquire this reporting fallback implicitly.

## Two mandatory gates

Windows/Android/iOS users retain their ordinary sign-in. Eagle Eye independently
resolves the human through configured same-host PACS then Reception and checks
its own user/module grants. Device pairing, product licenses, upstream identity
and local grants remain distinct. Either installed upstream is sufficient; both
are never mandatory. Unavailable/unverified providers fail closed with an explicit
error. Reception fallback follows explicit credential rejection only; no MongoDB
password-copy fallback is permitted.

## Wire contract, version 1

Keep existing paired TLS and device `Authorization: Bearer ...` on every request.
`POST /v1/auth/session` accepts exactly one of these forms:

```json
{"username":"synthetic-user","password":"synthetic-only"}
```

```json
{"provider":"pacs","upstream_token":"synthetic-upstream-token"}
```

Password exchange has no caller-selected provider. The explicit provider plus
upstream-token form remains a compatibility path for verifiable existing sessions.
Legacy provider-plus-password requests also follow server-owned PACS-first order.
Username alone is never evidence of identity. The
server selects the upstream origin; the caller cannot supply a URL, host, role,
subject or requested grants. Password login on PACS uses the RIS-aware socket
Login, followed by authoritative `/api/auth/verify`, not the local-only REST login.

Response: `user_session`, `expires_in` (seconds) and `user` with `principal`,
`provider`, `subject`, `username`, `enabled`, `echomind`, `imaging`, `crm`,
`secretary`, `modules`. No upstream token or password is returned. Sessions are
opaque, paired-device/center/person bound, process-local and expire in one hour.
Every protected request verifies upstream identity again and reloads local grants.
An upstream failure invalidates the session; server restart requires exchange again.

Add `X-Eagle-User-Session: <opaque session>` to jobs, results, cases, EchoMind,
Secretary, CRM and usage requests. `GET /v1/auth/me` revalidates and returns `user`.
`POST /v1/auth/logout` with `{}` invalidates this paired device's session.
Do not forward the workstation console administrator as a remote user.

`GET /v1/capabilities` remains paired-device discovery without patient data;
`user_auth` advertises version, requirement, configured providers and session header.
A configured provider is not proof of readiness. Auth/usage/capability discovery
does not grant inference or override licensing.

Errors contain a fixed `code`: 401 means missing/invalid/revoked human session;
403 means upstream identity succeeded but Eagle Eye approval/grant is missing;
429 means bounded login/upstream capacity; 503 means unavailable upstream contract.
Clients must distinguish these from network errors and preserve pending drafts
and durable job handles. Never replay inference automatically after an unknown
outcome. On logout, account or profile change, clear person-scoped sessions and
reject results still bound to the previous account.

No passwords or upstream/session tokens in source, disk, diagnostics, URLs or
fixtures. Passwords are transient sign-in material over verified paired TLS;
loopback upstream requests stay on the server. Never send passwords per inference.

## Grants and retained state

Newly observed upstream identities are stored under stable center/provider/subject
keys with all local grants denied. Username changes do not create a second user.
Unknown modules are denied; imaging choices derive from the server catalog.
Explicit administrator changes are required before AI admission. CRM still needs
its own Reception workflow session in addition to the human Eagle Eye grant.
The Server binds that workflow session to both paired device and verified human
principal; another human on the same device cannot replay it.
Secretary permission cannot grant its target imaging/CRM/EchoMind operation.

The Eagle Eye-owned `user_access.database` is separate from clinical MongoDB and
existing text/job history. Default: `user-access.sqlite3` beside the configured
job root. Provision ACLs for the intended console operator and service identity;
this database contains sensitive identity/audit metadata. `user_access.providers`
contains only configured same-host provider endpoints. Missing explicit providers
reuse the existing local PACS source where available; no provider grants default
access and a Reception-only setup does not require a PACS identity source.

`GET /v1/usage` now returns version 2, `scope=this_user`, `counts` and up to 100
recent `events`, with operation/outcome/request count and UTC epoch timestamps.
This access audit is distinct from legacy version-1 per-device token summaries;
clients must not treat the two response shapes interchangeably. Legacy device
usage is not retroactively attributed to people. Completion/token attribution
and full cross-client acceptance must be reported as separate gates.

## Reception authority and remaining acceptance

The source-backed `ino-admin-user-v1` adapter exchanges credentials with
`POST /api/AdminUser/getToken` and verifies JWTs through
`GET /api/AdminUser/verify-token`. It uses the returned stable database subject,
not a supplied username or locally decoded JWT. Missing protocol configuration
fails closed. See `RECEPTION_IDENTITY_CONTRACT_2026-10-09.md`.

The adjacent JavaScript source is verified; parity with the compiled Reception
executable and live contract acceptance remain unverified. Its verifier checks
JWT validity and user existence, but does not recheck `Deactive`. Login checks
that flag. An already issued upstream token therefore cannot currently prove
immediate upstream account deactivation. Eagle Eye grants are rechecked on every
request. Upstream deactivation qualification remains a release gate; no bulk
patient/user reads or guessed endpoint fallback may replace it.

Reception-only deployments can start without a PACS image source. They expose no
image modules and reject image submission with 503; this does not imply that
Reception supplies DICOM images. Case-dependent workflows still require an
authoritative clinical source. No service was activated by these source changes.


## AI settings foundation clarification (2026-10-09)

Server Settings owns same-host PACS REST/socket and Reception connections.
AI contains EchoMind, Eagle Eye, Agent and CRM with a Server-only Users subtab
beside CRM. Users is no longer a separate top-level settings tab.
The owner reaffirmed explicit per-user approval and service/module grants.
Agent uses the Secretary grant. New identities and modules remain denied.
PACS roster import requires user-management permission. Reception identities
appear after verified sign-in; its bulk roster contract remains unverified.
Local console accounts cannot replace PACS/Reception remote identity.
Existing lazy construction, administrator admission and audit remain in place.
Focused settings/identity/HTTP/provider verification passed 100 tests.
Native source GUI, required payload parity and activation remain pending.
This does not fix the AI usage native crash or redesign other AI connections.

## Prepared password-only admission source - 2026-10-12

[Implementation and compatibility gates](PASSWORD_ONLY_ORDINARY_AUTH_2026-10-12.md). Caller provider/upstream_token exchange is removed from the prepared source; ordered username/password authentication and internal sessions remain. Active Razi candidate02 is unchanged until reviewed immutable deployment. Client/Android/iOS migration and live acceptance are separate gates.
