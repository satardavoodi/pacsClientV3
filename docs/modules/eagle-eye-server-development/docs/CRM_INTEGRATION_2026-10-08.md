# Hosted reception CRM integration

Status: source integration candidate; live GUI, clinical migration and installed
package acceptance are pending. No active service was restarted or redirected.

## Verified source and preserved behavior

The reception CRM source is 1.32.6, not the separate older INO CRM project. The
installed Razi service binary matches its 1.32.6 delivery receipt; its separate
desktop is 1.7.0. All ten prompt files are preserved byte-for-byte from the latest
development source. Assess and command interpretation have development changes
beyond the installed prompt versions. Standard prompt override locations were
checked without finding additional overrides. The source receipt is
`modules/ai_imaging/eagle_eye_remote/crm/migration_manifest.json`.

The original brain, tool registry (39 tools), role policy, reception identity,
conversations, evidence, analysis artifacts and report catalog are imported under
`crm/vendor`. The original provider adapter is changed deliberately: hosted
completion enters the existing Eagle Eye company AI gateway and never falls back
to a standalone provider. Model selection belongs to the server; `crm_model` in
the private EchoMind settings overrides the preserved CRM build default.

## Runtime and UI boundary

AI > CRM supplies manual reception sign-in, Report/Analysis selection and a
conversation-backed question workflow. AI > Connection includes CRM controls in
both roles. Server controls attach an explicitly prepared private CRM directory;
client controls reuse existing Eagle Eye pairing/TLS. Passwords and reception
sessions are held in memory only. Network and configuration operations run outside
the Qt GUI thread. This first page does not yet expose the full original desktop
history, attachment/report viewing or prompt editor.

An optional `crm` server configuration starts one owned, loopback-only child
process lazily. The public surface is `/v1/crm/*` on the authenticated Eagle Eye
listener. Reception login remains authoritative and each reception session is
bound to its paired Eagle Eye client. Hosted roles cannot fall back to another
standalone installation. Command requests also require the existing license gate.

The hosted mode is read-only: Report and Analysis; legacy direct dispatch,
confirmation and Executive mode are unavailable. Writes are forced off in the
worker. Conversation metadata may still be edited through its owner-scoped API.
Configuration, host credentials, session secrets, user overrides, databases and
clinical state are not copied into source or client settings.

Admission allows one CRM request at a time and one per paired client. An AI
command also holds a shared EchoMind gateway slot. Existing API politeness and
small Mongo pool remain in the child, which yields CPU priority. Windows Job
ownership covers the virtualenv launcher and redirected interpreter. Lost worker
responses terminate owned work before releasing capacity, clear sessions and
never retry automatically. Request/response sizes and network timeouts are bounded.

This bounds concurrency, not hard memory or GPU utilization. Imaging resource
reservations remain separate. Unified hard resource enforcement, fair scheduling,
CRM usage aggregation, cancellation and progress during a busy command need a
further slice before high-concurrency deployment can be claimed.

## Configuration and migration

Private Eagle Eye server configuration may include:

```json
{"crm": {"config_dir": "D:/Eagle Eye Server/private/crm", "max_requests": 1}}
```

That directory must already contain explicit `server.json` and `roles.json` with
the correct center, absolute data root and session secret. Existing `echomind`
gateway configuration is required. A service restart applies the attachment;
saving it does not restart a service. No private directory has been attached to
the active Razi service in this work.

Before actual migration, decrypt/reprotect saved reception credentials for the
target service identity: the standalone service uses LocalSystem and Eagle Eye
uses LocalService. Preserve the authoritative service data root and inspect the
desktop's separate data root instead of merging by filename. Stage a protected
copy, compare record ownership/history and verify rollback before selecting it.
Never copy provider keys into the imported package. Do not start two writers
against the same conversation or snapshot store.

Both packaging definitions explicitly retain the lazy worker/UI modules and
compile the original reception_crm package with its prompts/catalog. Nuitka
requires explicit package inclusion rather than treating Python as data; see
[the official manual](https://nuitka.net/user-documentation/user-manual.html). PDFium 5.13.0 and PyMongo 4.18.0 match the
verified CRM development environment. A full frozen build and its service launch
are still mandatory; source tests are not installer acceptance.

## Evidence and remaining gates

The original standalone source baseline passed 1,315 tests with one skip. Hosted
guards exercise pairing, licensing, session ownership, routing, prompt hashes,
lazy role UI and a real isolated synthetic worker with 39 tools and writes off.
129 adjacent hosted/settings/builder guards and 108 imported
brain/conversation/prompt/budget/security guards passed after import.
The initial worker test exposed missing dependencies, Windows interpreter PID
redirection and an HTTPStatus mismatch; these were corrected and retested.
The Razi ownership guard also exposed asynchronous child termination; shutdown
now joins the actual owned interpreter before returning or admitting new work.

Source GUI acceptance requires the human-launched single source application,
manual sign-in and the existing test-control bridge, following AGENTS.md. The
bridge was unavailable at review time. Installed CRM and Eagle Eye services were
left running unchanged. Completion of deployment requires live read-only API and
UI workflows, private-state migration, frozen two-backend acceptance, controlled
activation and rollback evidence. Developer source parity is recorded separately
in the protected parity receipt; it is not running-service parity.

Strict route/query parsing prevents decorated command URLs from bypassing the
license, mode and shared AI admission checks. The dedicated query guard failed
before correction and passes afterward. Progress alone accepts a bounded
conversationId query.


## Fixed local connections and diagnostics (2026-10-12)

Connection > CRM provides Test CRM Connection. Hosted MongoDB uses fixed mongodb://127.0.0.1:27017/ with no user-editable endpoint. The same helper applies to the hosted worker and diagnostic. Reception API credentials/port and attachment roots remain in the private CRM server configuration; this slice does not unify those with Server Management. MongoDB storage-drive location is not a connection setting. Attachment folders must match the site layout.

The bounded isolated check authenticates to the configured Reception API without querying patient records, pings MongoDB, and checks configured folder metadata/read access without writes. Results are independent, including authentication rejection, unreachable API, unavailable MongoDB, missing folders and denied access. Local API probes bypass external proxy settings. The existing source/frozen CRM worker dispatch handles diagnostics before HTTP startup. Automated adapter coverage is not installed-artifact acceptance.

Verification: two fail-before guards; independent root suite 32 passed, exit 0, no reruns. Source-GUI acceptance and installed-build acceptance remain pending. Staging and actual Razi diagnostic results are recorded under generated-files/eagle-eye/crm-diagnostic-staging-20261012; no service activation is implied.
