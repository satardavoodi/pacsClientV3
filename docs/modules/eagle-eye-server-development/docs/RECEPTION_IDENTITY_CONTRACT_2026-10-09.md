# Reception identity adapter: source-backed AdminUser protocol

Status: implemented for explicit protocol `ino-admin-user-v1`; 48 synthetic
protocol/transport guards pass. No live login, patient query, Reception mutation,
service transition or successful live authentication is claimed.

## Primary evidence discovered on 2026-10-09

Public unauthenticated discovery of `/swagger/v1/swagger.json`, `/openapi.json`
and `/swagger/index.html` on the configured same-host Reception listener returned
HTTP 401. No credentials were used. The listener process was
`D:/api/server-interface.exe`; adjacent source was inspected read-only.

- `D:/api/index.js:289-290` imports `routes/AdminUserRouter.js` and mounts it at
  `/api/AdminUser`.
- `D:/api/routes/AdminUserRouter.js:277-351` defines `POST /getToken`, consuming
  `{username,password}`. It queries ClinicUsersModel with a password comparison
  and rejects deactivated accounts (`Deactive:false` or null). Success returns
  `{success:true,token,user:{id,username,...}}`. Subject is database `_id` and
  canonical username is database `User`, rather than a caller assertion.
- Lines 254-274 implement `verifyToken` with upstream `jwt.verify`, rejecting
  missing, invalid and expired tokens. No JWT signing material was copied.
- Lines 364-404 define `GET /verify-token`, applying that verifier, then fetching
  the database user by the verified token's `id`. Success returns
  `{success:true,user:{id,username,...}}`; a deleted account returns 404.
- Lines 484-513 expose other lookup methods, but neither projects Deactive.
  The general user-list endpoint does project it, alongside password-related and
  personal fields for all users; that list was NOT queried or used as a verifier.

The old CRM API map documented only `/api/auth/login`; this new explicit protocol
is based on primary server source rather than guessing that old route's identity
schema. Adjacent source inspection does not prove compiled executable/source
parity. Human-authorized live login/verification remains a separate acceptance
requirement before deployment enables this protocol.

## Configuration and boundary

`user_access.providers.reception` supplies:

```json
{
  "protocol": "ino-admin-user-v1",
  "base_url": "http://127.0.0.1:8080",
  "timeout": 8
}
```

The origin accepts only 127.0.0.1, localhost or ::1 (bracketed IPv6). Remote hosts and control whitespace are rejected. Configure the actual local Reception
origin, not the example. In the inspected source, global index.js authorization
allows localhost through to route-level authorization, while getToken is not in
its nonlocal public-route list. Thus nonlocal getToken access may be rejected
before credential processing. A same-machine loopback origin can reach the route;
getToken still performs its own real password validation and verify-token still
performs JWT signature verification. Never substitute a fabricated localhost
principal or bypass those route-level checks. Confirm the actual deployed route
behavior during authorized acceptance; do not auto-fallback between hosts/routes.

Without the explicit recognized protocol, `available=False` and both methods
raise `ReceptionIdentityUnavailable` (status 503). With valid configuration,
`available=True`; this indicates supported protocol selection, not live readiness.
No arbitrary login/verify path or fallback authority can be configured.

`ReceptionIdentity(config).login(username,password)` POSTs to
`/api/AdminUser/getToken`, then mandatorily verifies its token with
`GET /api/AdminUser/verify-token`. Login and verifier identities must match.
`verify(upstream_token)` returns `{subject,username,provider:'reception'}` from the
upstream verification response. It never decodes JWTs locally or trusts the
username supplied by the caller. Zero/local sentinel and malformed subjects are
rejected. Tokens/passwords are not retained in the adapter or logged.

Transport uses the same configured origin for both fixed routes, disables
redirects and environment proxy inheritance, verifies HTTPS certificates,
bounds connection/read time and response size (64 KiB), and sanitizes upstream
errors. No retries or PACS/local/anonymous fallback occur. HTTP is supported for
explicitly configured same-machine Reception deployment; it does not provide TLS
and should not be selected for untrusted remote transport.

## Explicit revocation limitation: pending acceptance gate

The source verifier validates JWT signature/expiration and current user existence,
but does not select or test Deactive on verification, and exposes no documented
per-token logout/revocation check. Disabling an account after token issuance is
therefore NOT proven to revoke its existing token. No safe subject-specific
Deactive endpoint was found in the inspected AdminUserRouter. New login rejects
disabled accounts. Immediate disabled-account/token revocation requires an
upstream verifier enhancement; this adapter must not be described as covering it.
No Reception source changes were made.

## Acceptance and synchronization

48 synthetic tests pass; real Reception login/token verification and affected
mobile GUI acceptance are pending. Shared UserAuthority integration, immutable
Razi staging, mirror reconciliation and complete Developer parity belong to the
coordinating authentication workstream. These files have not activated any live
service and no build handoff is authorized by these tests.

## Explicit administrator roster import (2026-10-12)

The Server Users console offers distinct PACS and Reception imports. Reception
uses the source-backed `GET /api/AdminUser/getCenterUsers` route verified at
`D:/api/routes/AdminUserRouter.js:17-24`. Before requesting the roster, it performs
a fresh password login, verifies the returned token, and requires the authoritative
Admin flag. The bounded response is projected to `_id`/`User` only; deactivated
accounts are excluded. Passwords and all other upstream personal fields are not
persisted or displayed. Import does not grant permissions or replace the two-stage
request authentication contract. User audit recording remains enabled; the console
loads and displays history only when Show selected user logs is selected.

Synthetic guards cover projection, administrator rejection, and opt-in history.
Live import and affected GUI acceptance remain separate qualification steps.
