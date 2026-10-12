# Shared external AI connection foundation - 2026-10-09

The Server AI > Connection hub owns presentation of the existing backend,
Company Authentication and EchoMind/Eagle Eye/Agent usage panels. Existing widget
owners and save handlers remain intact. The company display name is
Eagle AI Brain; this is a product label, not a new network endpoint.

Verified source routes:
- Hosted CRM provider.py uses the server EchoMind core with its private directory.
- Hosted Secretary service.py uses that core and the EchoMind configuration context;
  image generation still has its own GapGPT endpoint.
- Hosted EchoMind service.py retains both company report endpoints and the GapGPT
  Turbo route. A shared connection must preserve Turbo-first/company fallback.
- Lumbar llm_backend.py still resolves a backend through EchoMind settings. Its
  server execution context must be verified before claiming private-config parity.
- Local imaging models do not require an external provider connection.

Pending: bind server-console editing to the running service private configuration
with authenticated administration and revision checks; inventory every image,
search and speech endpoint; centralize endpoint overrides without changing approved
speech order or personal-API isolation. Desktop settings are not proof that the
service private configuration changed. No credential, endpoint or live service
activation was changed by this presentation slice.

Validation: five offscreen startup/settings guards passed locally. Native GUI,
real provider acceptance and complete Developer snapshot parity remain pending.

Owner terminology: Eagle AI Brain is the company-managed LLM connection. Existing center access codes select the company account; they are not server-console passwords or provider API keys. Preserve the existing code registry and never publish its contents.

Owner correction: the connection title is Eagle AI Brain. Server 1 - GapGPT maps to the existing company backend identifier (company). No model, prompt, personal API setting, speech order or report fallback policy is changed. This is a connection alias, not a new provider or forced migration of native Assistant endpoints.

## Server 1 private authentication and accounting implementation

The server Connection now has a dedicated Eagle AI Brain panel, independent of
optional EchoMind UI visibility. Its center-code form validates the existing
private centers.json encrypted credential registry and atomically updates only
api_key/llm_backend in the private settings.json with a revision check. Existing
models/prompts remain unchanged. The old desktop-only authentication/backend
panels are hidden in Server mode, rather than used to configure the service.

Hosted company GapGPT POST calls pass through brain_connection.send at the
shared server HTTP boundary. A private brain-usage.sqlite3 records category,
state and reported token counts only. It stores no prompt, response, user name,
credential or model. It totals calls across models, records failed/pending calls,
and distinguishes missing usage from zero. Native Assistant/company-report
endpoints, personal API mode and audio transcription are excluded. Existing
transport timeout, bounded response loading and report fallback remain intact.
If usage storage cannot admit a call, the provider is not contacted. There is no
automatic replay for accounting failures or provider timeouts.

Count semantics: upstream calls are not logical user submissions. Existing
workflow request panels remain visible separately. Secretary act is Agent;
ask/guide/help_ticket is Secretary EchoMind. Asset provider calls are Agent.
CRM is explicitly tagged CRM. Shared hosted EchoMind calls are EchoMind. A
request with multiple LLM steps contributes multiple provider calls and their
reported tokens, without duplicating its existing workflow request record.
Historical calls before activation cannot be reconstructed as precise shared
transport usage. Interrupted pending calls remain pending, never fabricated as
completed. The native lumbar adapter currently uses offline_lumbar.run_snapshot;
legacy/client lumbar LLM contexts have not been qualified by this change and are
not claimed migrated. Future server LLM adapters must supply a source category
and the shared private runtime context.

Validation: 88 focused local guards passed (Brain/private authentication, usage,
CRM, Secretary, fallback and settings). A broader first run had a stale CRM tab
expectation (corrected to include Server Users) and a dental-panorama usage-fixture
failure still outside this change. Native GUI, real-provider acceptance and
complete Developer parity are not established by these tests.

Razi receipt: revisions/20261009-brain-usage/source passed the same 88 focused
guards; transferred change-file hashes match the control computer. It is an
inactive immutable candidate. Runtime config/.venv junctions remain host-private.
Full repository/payload parity and native/provider acceptance remain pending;
the active service and desktop shortcut were not transitioned. The active old
service therefore does not produce records in this new transport ledger yet.

## Ordinary human admission contract - owner decision 2026-10-10

For EchoMind, Eagle Eye imaging, Secretary planning and CRM, an address/port and
the ordinary user's existing credentials are sufficient. A device bearer, client
certificate, private key, pairing QR or manually installed client identity is NOT
an admission requirement. Agent PACS execution remains a separate paired gateway;
this change grants no native execution capability and does not change that gateway.
The owner explicitly requested ordinary HTTP as well as existing HTTPS compatibility.
HTTP transmits credentials/content without transport encryption; this is a recorded
owner transport choice, not an implicit TLS-verification bypass. HTTPS continues
normal certificate/hostname validation.

| Boundary | Shared Windows / Android / iOS contract |
| --- | --- |
| Discovery | Bounded public GET `/v1/capabilities`; no secrets or private configuration |
| Admission | POST `/v1/auth/session` with `{username,password}` |
| Authority | Server verifies PACS first; Reception only after explicit credential rejection |
| Session | Existing `{user_session,expires_in,user}` response; opaque server-owned session |
| Requests | `X-Eagle-User-Session`; device certificate/bearer not required |
| Grants | Enabled user plus relevant module permission; imaging submodule grant also required |
| Denial | 401 missing/invalid/expired identity, 403 unapproved or denied module; no paid work |
| Isolation | Server derives persistence owner from verified principal, never caller identity fields |
| Compatibility | Existing explicitly paired callers remain supported without changing Agent PACS |

Preserve profile/logout/session invalidation, bounded source-IP login attempts,
upstream revalidation, licensing, request identity and server-owned prompt/model
selection. Two humans must not read/cancel each other's private jobs, artifacts,
text history or CRM session. Existing explicitly authorized center-case sharing
remains bounded to this configured center and current module grants.

Affected Android components: ServerProfile, EchoMindSettingsStore, EagleEyeClient,
EagleEyeTls, server settings and hosted CRM transport. Affected iOS components:
server profile/settings, Eagle transport/auth session and hosted AI/CRM callers.
Native implementation details can differ; wire behavior and admission cannot.
Retain separate source, tests, build, native UI and real provider acceptance per
platform. A connection probe or one platform's pass does not prove the other.

Older active revisions require mTLS for both LAN and public addresses. New source,
activation and mobile test status must be identified by fresh receipts; saving this
contract does not activate an implementation.
