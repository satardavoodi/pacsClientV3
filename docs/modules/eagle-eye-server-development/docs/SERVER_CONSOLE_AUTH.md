# Eagle Eye Server console authentication

Owner decision: 2026-10-09. Applies to Eagle Eye Server only.

## Deployment architecture

Reception, PACS Server and Eagle Eye Server are three applications installed on
the same customer computer. Reception owns reception records; PACS owns image
storage and study identity. Eagle Eye consumes their authorized local APIs and
controlled local file access, executes imaging and hosted AI workflows, and owns
company LLM communication. Loopback is the default for same-host dependencies;
the Eagle Eye listener for paired LAN clients remains a separate configuration.

## Console identity

The Server console requires its own authenticated administrator session. The
owner-requested account name is `AI-PACS`, with role `superadmin`. Its password
is private deployment state, never a compiled default or source/document fixture.
Local Login and Demo fallback cannot authorize the Server console.
Standard DICOM Workstation Client behavior is preserved.

## Upstream administrator console admission (2026-10-10)

The owner additionally authorizes existing PACS and Reception administrators to
sign in to the Server console. The worker first checks the protected local
superadministrator, then authenticates against configured same-host PACS, then
Reception only after PACS explicitly rejects the credentials. A PACS outage or
an authenticated PACS non-administrator does not trigger an authority fallback.
PACS admission requires `admin` or `system_admin` from its verified identity
endpoint. Reception admission requires the boolean `admin: true` from fresh
password-validated AdminUser login plus a matching independently verified token
identity. Merely having an AdminUser account or AI usage grants is insufficient.
Neither upstream credentials nor tokens are retained in the console session.
Offline entry stays disabled; remote module grants remain a separate gate.

The previous implementation routed Server sign-in exclusively to the private
local verifier, which explains why existing upstream administrators were denied.
Three admission guards failed before the entry point was added. Automated
verification, immutable Razi staging and human GUI acceptance are recorded
separately; code changes alone do not prove the desktop launcher is updated.

Console identity does not manufacture a PACS token, reception session, paired
client certificate or Server license. Those authorities remain independent.
Dependent operations still require their own credentials and permissions. This
slice admits the console; it does not implement new remote administrative APIs,
fine-grained management permissions or a complete session/revocation system.

The explicit provisioning tool is `tools/eagle_eye/provision_console_admin.py`.
Provision an absolute directory with owner/SYSTEM-only ACLs first, then run the
tool with `--store` and `--username`; enter the password at its hidden prompt.
No password command argument exists. Existing accounts cannot be replaced.
Provision separately on every host and under the intended Windows console user.
The Windows verifier is user-bound DPAPI protected, using a random 32-byte salt
and PBKDF2-HMAC-SHA256 with 600,000 iterations. The default store is
`%ProgramData%/AI-PACS/EagleEyeServer/security/administrator.bin`.
Never bundle this file, copy it between hosts or share the provisioning password
through source configuration. New customer installations require explicit private
provisioning; missing or corrupt storage fails closed.

Password verification runs outside the Qt GUI thread. Server sign-in never loads
or saves the workstation's legacy remembered plaintext credentials. Failed
attempts have process-local backoff (60 seconds after five failures); restarting
the console resets that counter. Console session handles expire after eight hours
and are checked at main-window admission; an already open window is not
automatically locked by this slice. Durable lockout, password change/recovery,
idle locking and management-action authorization remain follow-up work.

## Verification and build separation

Twenty-one focused/adjacent synthetic guards passed on the control PC; seventeen
authentication/license guards passed on the staged Razi source. Two initial policy
guards failed before implementation at the unguarded offline/window boundary.
Live source GUI acceptance is pending: the existing control client cannot reach
an enabled Test Control Server. Human sign-in is required; never automate it.
The private `AI-PACS` account was separately provisioned on both hosts under their
respective Windows operator identities. Razi candidate
`20261009-server-console-auth/source` preserves 8,402 baseline source/resource
files and overlays 32 hash-verified source/document files. The active source was
not changed. Full Developer parity remains blocked by pre-existing cross-workstream
deltas (including active server/Secretary versus local source); this candidate is
not a build handoff. Activation, live GUI and frozen installer acceptance remain
pending, not implied by local tests or staged files.

`main.py` selects the role before constructing the shared login dialog. Source
launch must explicitly select `--eagle-eye-mode server` with its deployment config;
frozen role selection uses the installation edition. Server behavior must never
be inferred merely from the directory name. PyInstaller follows the explicit
runtime import; Nuitka additionally lists the authentication module explicitly.
No secret store or universal password is included in either product's build.

## Identity and per-user authorization review — 2026-10-09

Status: investigated design, not implemented user management.

The workstation login calls `SocketService`, which creates
`modules.download_manager.network.socket_client.SocketDicomClient`; its `login`
sends the `Login` socket operation to PACS. PACS source
`servers/socket_server.py` delegates to RIS first when enabled, otherwise to
`database/user_management.py`. PACS `users`, `user_sessions` and
`system_settings` are MongoDB collections. RIS-authenticated identities and
sessions are also represented locally by PACS; this does not make MongoDB the
upstream identity authority. A bounded read on Razi confirmed
`ClinicWebsite.system_settings` contains `ris_config` with `enabled=true` and
`fallback_to_local=true`. No user records, tokens or passwords were retrieved.
Thus a successful existing workstation login may be Reception/RIS or local PACS;
the API must attest the source rather than guessing from a username.

PACS source exposes `GET /api/users` under `manage_users`. Imported metadata must
come through authorized APIs, never by copying password hashes or reading the
clinical users collection directly from Eagle Eye. The current PACS roster may
contain only previously synchronized RIS identities, so completeness of a
Reception roster requires a separately verified Reception listing API.

Eagle Eye currently authenticates paired device tokens/certificates. Its API
`owner` is the paired client, not the logged-in person. Imaging job state retains
JSON records; EchoMind/Secretary retain `history.sqlite3`. Usage groups are per
module/workflow and paired client; they are not a reliable per-person audit.
Hosted CRM separately requires a Reception session bound to that paired client.
The newly provisioned console administrator is another distinct local identity.

The requested Server-only Settings > User page must manage source-scoped stable
identities (center, provider, upstream immutable ID), explicit local Eagle Eye
accounts and separate Eagle Eye grants. Same-named PACS/Reception accounts must
never be merged automatically. Upstream authentication proves identity; Eagle Eye
approval grants access. Imported/new users and newly introduced imaging modules
start denied until a superadministrator grants access. Account synchronization
must not overwrite local grants, and upstream-disabled accounts must be denied.

Requested grant groups: EchoMind, imaging with individually selected module IDs,
CRM and EchoMind Secretary. Imaging choices must derive from the server catalog
(currently breast, bone-age, brain, brain-lesions, lumbar, lumbar-marrow, alignment,
total-spine); additions appear unselected. License entitlement and enabled/ready
function availability remain independent gates. An Eagle Eye-only account with
an AI grant must still acquire legitimate PACS/Reception access for protected data.

Enforcement belongs on all relevant Server API routes before retrieval, inference
or LLM work, with user sessions verified server-side and bound to paired devices.
Do not trust a username supplied in a request. Reads, corrections, result sharing,
asset requests and cross-module Secretary tools require explicit policies too;
Secretary permission cannot bypass an imaging or CRM denial. Permission changes
and account disabling must invalidate admission promptly, without blindly killing
clinical work. Completed-result access after license expiry is an explicit policy,
not an accidental extension of computation permission.

A separate Eagle Eye-owned transactional identity/grant/audit store is required;
SQLite fits the existing Server history stack, while dedicated Mongo collections
remain an alternative requiring a separate schema/access decision. Do not write
Eagle Eye grants into PACS/Reception-owned user collections. Record login outcomes,
grant changes and usage events with stable actor/device IDs, UTC timestamps,
module/function, unique request/job IDs, status, duration and reported token usage.
Keep clinical payloads and credentials out of the audit. Distinguish refused,
failed and completed calls; retries/reconciliation must not double-count usage.
Unknown historical device-only usage cannot be retroactively assigned to people.

The subsequent owner decision and implementation are recorded in
[USER_AUTH_PROTOCOL.md](USER_AUTH_PROTOCOL.md). That decision supersedes the
Eagle Eye-only account suggestion above: remote human identities must come from
PACS or Reception. The following delivery-order paragraph records this earlier
review checkpoint, not the current source implementation status.

Suggested delivery order: authoritative identity/session adapter and Server-side
grants; audited User UI and protected local accounts; per-person usage reporting;
Client/mobile integration, source-GUI acceptance and immutable Razi activation.
Full Developer parity and build gates remain mandatory. No User tab, delegated
user session or per-person enforcement was delivered by this review.


## Console username case (2026-10-09)

The owner requires uppercase and lowercase account names to identify the same
provisioned administrator. Username comparison uses casefold; returned identity
retains its provisioned spelling. Password comparison remains exact, with the
existing salted verifier, lockout and session policy unchanged. No duplicate
account or new password store is created. Twelve synthetic console guards pass.
A fresh human source login is required for live acceptance.
