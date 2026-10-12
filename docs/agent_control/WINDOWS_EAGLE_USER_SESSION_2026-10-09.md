# Windows Eagle Eye human sessions

Canonical protocol: `../modules/eagle-eye-server-development/docs/USER_AUTH_PROTOCOL.md`.
This Windows integration preserves device bearer authentication and paired TLS.

## Owner correction: ordinary login only (2026-10-09)

This section supersedes earlier provider-choice/Reception-entry descriptions below;
those sections are retained as historical implementation receipts, not current UI.
No PACS/Reception selector, separate Eagle Eye sign-in or Reception-only Windows
workspace is part of the current contract. The ordinary login UI and its existing
persistence behavior are unchanged.

The sole authorized AppHandler overlap is immediately after a true successful
socket login: `login_generation = token_manager.set_token(token, user)` followed
by `user_session.capture_login(username, password, token_generation=login_generation)`.
Demo/offline and server-console admission never capture client human credentials.
`set_token` returns its atomic login generation, so a late capture cannot bind old
credentials to a newer account. Capture performs no network or persistence I/O.

At the first protected AI/CRM request, the parent worker sends only
`{username, password}` to `/v1/auth/session`. The server owns PACS-first then
Reception resolution after an authoritative identity rejection. A server-resolved
PACS or Reception receipt is accepted, cached and reused. Local module-grant 403
never causes client reauthentication, provider selection or fallback. Existing
upstream-token-only integrations retain their explicit PACS compatibility path.
The child IPC still receives only opaque session/lease identity, never credentials.
Account/logout/profile invalidation clears captured credentials immediately and
keeps the bounded exact-session logout behavior described below.

CRM workflow login no longer calls `authenticate_user('reception', ...)` and cannot
replace the ordinary user's Eagle Eye principal with credentials typed into the
Reception workflow form. Its own CRM workflow credentials/session remain separate.
The legacy worker helper accepts its old provider argument for call compatibility
but omits it from credential exchange; no new UI calls that helper.

Six automatic-login guards fail against the captured pre-correction user-session
module, including the extracted actual socket-login method. New guards cover
credential capture timing, no capture I/O, session reuse, server-resolved Reception,
403 with no fallback, logout and concurrent account-change rejection. Final test
counts and exact source paths are in the provider-correction receipt. AppHandler
changes outside the two-line capture hook remain owned by the server/UI workstream.
Native ordinary-login/Slicer GUI acceptance and combined Razi parity remain pending.

## Historical implemented boundary

`AppHandler._authenticate_with_socket` already passes the actual successful PACS
socket Login token to `SocketTokenManager.set_token(token, user)`. The new
`eagle_eye_remote.user_session` reads that atomic in-memory token snapshot and
exchanges it through `/v1/auth/session` with provider `pacs`. It never reads
`AppHandler._server_session` or the console administrator Qt property. No
passwords, upstream tokens or opaque user sessions are written by this feature.

`Client.authenticate_user(provider, username, password)` also provides explicit
worker-only PACS/Reception sign-in with transient credentials. It invalidates the
previous human context before authentication, retains only the confirmed opaque
session in memory and never switches authority after failure or expiry. The
`user_session.confirmed_admission(client)` helper is a pure in-memory check for
AppHandler immediately before opening Home; it returns `generation`, `provider`
and `principal`, with no password/token/session material. It raises 401 after
account change, cache invalidation or expiry. It performs no network or disk I/O.
AppHandler remains owned by the server workstream.

Existing Reception CRM sign-in invokes `authenticate_user` with
`provider=reception` before its
separate CRM workflow login. CRM now uses central `Client.open` with both the
human header and the independent `X-CRM-Session`; it no longer bypasses human
admission through a direct opener call. Sign-in 401/403/429/503 errors are distinct.

Central `Client.open` adds `X-Eagle-User-Session` to protected requests, including
jobs/results, shared cases, EchoMind, Secretary, CRM and usage. Capabilities and
session exchange remain device-authenticated discovery/bootstrap. Exchanges are
serialized separately from inference; inference is never automatically replayed.
HTTP 401 and 403 remain distinct typed errors with sign-in/access messages.

Each successful token assignment or clear increments a login generation and
immediately clears the shared session cache. Existing clients and response reads
reject changed generations. Default-config clients also reject changed connection
profiles; sessions are cached separately by connection configuration. Durable
analysis handles contain a hash of the server-confirmed human principal, not the
opaque session. Unbound legacy handles and another person's handles fail closed.

Version-2 usage is validated as `scope=this_user`, `counts`, `events` and rendered
as operation/outcome/request counts. It is never converted to version-1 device
token accounting. Existing local server administration accounting stays separate.

## Owned files and coordination

- `modules/network/socket_token_manager.py`
- `modules/ai_imaging/eagle_eye_remote/{client,user_session,user_usage,administration}.py`
- `modules/EchoMind/remote_backend.py`
- `modules/EchoMind/secretary/remote_planner.py`
- `PacsClient/pacs/workstation_ui/settings_ui/ai_usage_settings.py`
- `modules/ai_imaging/eagle_eye_remote/crm/client.py`
- `PacsClient/pacs/workstation_ui/settings_ui/crm_settings.py`
- `tests/code/ai_imaging/test_windows_human_session.py`
- Applicable EchoMind plugin mirrors and this evidence record.

Legacy transport fixtures were reconciled with an explicitly approved synthetic
human in `tests/code/ai_imaging/human_access_fixture.py` (opt-in fixture, not an
authentication bypass). Affected tests: `test_eagle_eye_remote.py`,
`test_case_realtime_http.py`, `test_eagle_eye_mtls.py`, `test_ai_usage_requests.py`,
`test_ai_usage.py`, `test_remote_review_modules.py`, and EchoMind tests
`test_eagle_eye_echomind.py`, `test_mobile_source_contract.py`,
`test_secretary_server.py`. Imaging conftest exposes the fixture without autouse.
`test_crm_integration.py` now independently verifies missing human identity (401)
and a confirmed human with an unavailable product license (403), while preserving
the separate Reception CRM workflow session header.
`builder/eagle_eye_client_payload.py` stages the required new session module so
the isolated client fails with a sign-in error rather than a missing module.
The exact owned hashes are in the private ignored receipt
`generated-files/eagle-eye/windows-human-session-20261009/client-integration-receipt.json`.

AppHandler, Server handler/auth backend, Settings User tab, build includes,
canonical protocol and immutable Razi staging remain with the server workstream.
No AppHandler source, server auth source, live service or Razi activation was
modified by this Windows slice. The server owner must preserve the observed
SocketTokenManager handoff and call `clear_token()` if adding in-process logout,
account/profile replacement or a console-role transition. Token clearing is not
equivalent to a successful server-side `/v1/auth/logout` audit.

## Verification and open acceptance

- Eight selected guards fail against the original Git transport loaded into an
  isolated test process, without rolling back or overwriting the dirty checkout.
- 64 focused Windows/auth/PACS/Secretary/session-file guards passed together,
  including production Client against a real loopback synthetic HTTP handler,
  upstream revocation, grant denial, stale in-flight responses and human-bound
  durable handles. This is synthetic integration, not a live clinical login pass.
- Additional affected suites passed: 90 HTTP/TLS/case/EchoMind/mobile/Secretary
  guards; 32 human-v2/legacy-admin usage scenarios; 64 adjacent usage/review/
  settings/staged-payload guards. Four focused suites total 250 passes (exit 0).
  The eight baseline failures were expected, not a current-suite failure.
- The documented local Test Control `ping` failed because its listener was absent.
  No source app was restarted, no authentication automated and no Razi activation
  performed. Final global mirror verification passed: 528 pairs match. Both owned
  EchoMind mirrors were synchronized without modifying Education source.
- After adding explicit Reception and CRM transport integration, the expanded
  affected run produced 217 passes and two legacy CRM fixture failures (still
  assuming paired-device-only admission). Those fixtures were corrected with real
  approved synthetic human sessions; the targeted CRM/human rerun passed all 36
  tests, including 24 dedicated Windows human-context guards. The separate latest
  auth/PACS/Secretary/session-file run passed 74 tests before the final three
  focused sign-in guards were added. Do not describe this as a repository-wide pass.
- Reception-only client protocol and existing CRM sign-in are supported by
  explicit transient authentication and a real loopback HTTP gate test with no
  PACS provider or token. The server workstream subsequently implemented initial
  Windows entry in AppHandler and `eagle_eye_remote/client_login.py`: an explicit
  authority dropdown, transient worker credentials, old-identity clearing, no
  Reception remember/offline mode, and a captured generation/5-second admission
  receipt checked again immediately before constructing Home. Read-only review
  found no additional actionable issue in this handoff boundary. The combined
  initial-entry/server-policy/Windows-session suite passed 34 tests (exit 0),
  including seven initial Reception-entry guards. These two source paths remain
  server-workstream-owned and are excluded from this Windows slice's owned hash
  list. Native initial login and complete Reception-only Windows acceptance remain
  unverified; no live Reception login is claimed.
- A separately launched viewer has no inherited human singleton. The default
  resident Slicer path now uses the private parent RPC lease described below.
  Legacy nonresident launches have no human handoff and remain fail-closed.
- Native login/logout/role-change and GUI result-application acceptance remain
  pending. Read-time account checks do not independently prove every GUI callback
  rejects a response delivered before a subsequent account switch.
- Razi Developer source parity and activation are deliberately pending the server
  workstream's immutable combined staging. No build handoff is claimed.

## Post-parity identity boundary review

The combined source owner reported 8,454 matching source files before this review.
The supplemental manifest requires combined restaging; none of these new changes
is covered by that earlier parity claim. No executing Razi source or server
backend was overwritten. Read-only remote audit captured the inactive candidate's
pre-edit hashes and source bytes before preparing the supplement.

`ResidentService.analyze_snapshot` already performs remote vertebrae inference
inside the workstation parent worker. Its immutable geometry/reference checks
remain intact. The actual child sender `AIPacsOfflineLumbar` now receives human
admission through the existing authenticated resident RPC, not credentials in
environment variables or ready files:

- `AIPacsBackgroundRuntime` installs a bounded four-request child identity queue
  and advertises `user_identity_version: 1`. Authenticated `identity_poll` and
  `identity_reply` operations run independently of scene commands.
- `LocalRuntime` owns a background broker using its existing private localhost
  RPC token. Only the parent exchanges PACS/Reception authentication. The child
  receives an opaque server session, principal and random process-local lease.
- Acquisition matches parent URL, connection profile and device-token digest.
  Reuse and response consumption validate the parent account generation, profile
  and unexpired confirmed admission. Up to 64 in-memory leases are bounded by
  the parent's one-hour session lifetime; a long inference is not rejected merely
  for taking over 30 seconds. Parent loss times out within eight seconds.
- Child sign-in cannot forward passwords. No inference replay, provider fallback,
  generated code execution, decoder or rendering changes were introduced.
- The child stdlib payload adds `parent_ipc.py` and `session_revocation.py`.
  Parent freezing must include `human_session_ipc`, `parent_ipc` and
  `session_revocation` alongside `user_session`. Build ownership remains with
  the combined source owner; no build or release was started here.

`user_session.clear` removes local admission immediately and queues bounded,
best-effort POST `/v1/auth/logout` cleanup on a daemon worker. Each task contains
only the original URL, pinned TLS opener, device bearer and exact opaque session.
It does not consult the new profile or retain a password/upstream PACS token.
Only logout is retried by neither layer; cleanup failure does not restore local
admission. The 64-entry queue and two-second transport deadline bound cleanup;
unreachable-server logout remains best-effort and can leave the old server token
until server expiry/revalidation. Account/profile changes and HTTP 401 take this
path. The separate website identity disconnect is not Eagle Eye logout.

CRM relogin clears its old workflow session before both human and CRM exchanges.
The isolated stdlib client recognizes missing host modules and returns typed 401
without network access. Parent-owned server CRM principal binding remains separate.

Verification: the pre-edit inactive candidate's `user_session.py` fails both the
identity-bridge capability and exact-session-clear guards. The new suite exercises
actual private TCP RPC with an isolated staged child package, account changes
before response consumption, mismatched profile/device, parent timeout, bounded
queue, old pinned transport logout and background worker drainage. The combined
Windows/CRM/server-HTTP/Reception-entry/resident suite passed 76 tests before the
two explicit baseline guards were added; the final focused count is recorded in
the supplemental manifest. Native Slicer inference and GUI acceptance remain
pending. The documented control `ping` still fails because no Test Control Server
is listening; no installed app or duplicate source instance was launched.

Private supplemental receipt and ZIP:
`generated-files/eagle-eye/windows-human-session-20261009/post-parity-identity-review-manifest.json`
and `post-parity-identity-review.zip`. Check expected inactive-candidate hashes,
reconcile concurrent edits (especially shared documentation), stage a new immutable
combined revision, regenerate full parity and verify the running snapshot before
function/GUI acceptance. The candidate is not automatically activated by this slice.
