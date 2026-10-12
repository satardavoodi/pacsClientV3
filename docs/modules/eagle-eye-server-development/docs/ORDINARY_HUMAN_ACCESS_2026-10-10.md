# Ordinary human access without device pairing

Owner decision: EchoMind, Eagle Eye imaging, Secretary and CRM use verified human
login without a device bearer or client certificate. Agent PACS pairing and its
separate execution gateway are unchanged. This is a default runtime contract,
not a test flag. No upstream credentials or patient information belong in logs.

## Wire and authority

- Anonymous `GET /v1/capabilities` returns bounded server-owned capability data.
  Deployment metadata is limited to qualification, mode, release ID, version and
  edition; private paths and arbitrary configuration fields are omitted.
- `POST /v1/auth/session` accepts `{username,password}` and returns the existing
  `{user_session,expires_in,user}`. PACS is checked first, Reception only after
  authoritative identity rejection; provider outages and local grant denial do
  not fall through. Existing upstream-token exchange remains compatible.
- Protected ordinary APIs require `X-Eagle-User-Session`. Missing, expired,
  restarted or upstream-invalid sessions return 401. Disabled feature/module
  grants return 403. User approval remains a separate gate from upstream identity.
- Login attempts are bounded per actual socket peer address (not forwarded
  headers or device names), with 4096 active minute buckets and four upstream
  authentication slots. Sessions remain bounded and process-local.
- Legacy paired callers can still send their bearer. Known bearers must satisfy
  their configured certificate pin; unknown nonempty bearers fail closed. A
  bearer does not replace human admission or grant checks.

## Isolation and sharing

After upstream verification, ordinary processing owner is
`human:` plus SHA-256 of the server-verified principal. Caller usernames, device
IDs and headers cannot select it. Jobs, idempotency, artifacts, private histories,
Secretary assets and CRM session bindings use this owner. The same person retains
their own work across devices; different people on one device remain isolated.

Existing explicitly authorized center case reads remain shared. The server admits
a verified human owner to its configured center only when AccessStore's authority
center equals the case service center. Legacy paired outside-center callers remain
denied. Membership storage is bounded to 4096 entries and snapshot iteration is
locked. No arbitrary device is appended from a request field.

EchoMind/Secretary/CRM admission uses 64 bounded lock stripes for human owners;
global processing slots remain unchanged. Collisions can reduce concurrency but
never share content or identity. Anonymous requests allocate no owner locks.

CRM still requires its existing Reception credential exchange and
`X-CRM-Session`, bound to the verified human principal and processing owner.
Removing device pairing does not remove Reception authentication, CRM grants or
its read-only command policy, and does not add clinical records to model inputs.

## HTTP and HTTPS

The same existing listener accepts ordinary HTTP and HTTPS when a server
certificate is configured. The accept loop does no TLS work. A bounded worker
peeks at the first byte under a five-second timeout, then performs a TLS handshake
or passes an HTTP request to the handler. There are at most 64 connection workers.
TLS client certificates are optional at transport; presented certificates are
verified and paired bearer requests still require matching pins. HTTPS clients
must continue validating the server certificate; no verification bypass is added.

## Verification and rollout

Synthetic network guards cover real HTTP and verified HTTPS without client
certificates, two-user job/read/cancel/artifact isolation, anonymous capability
privacy, stalled-peer independence, revocation/expiration/restart, peer rate
limits, and private history / Reception session isolation. The initial anonymous
capability and ordinary login guards failed before implementation. Existing
paired, user-authority, case, Secretary and CRM guards remain required.

This receipt describes canonical source work only. Coordinator-owned immutable
Razi staging, full-source parity, private settings review and controlled activation
are separate gates. Native GUI, Android/iOS and actual provider acceptance are not
established by the local HTTP harness. No provider submission or Razi transition
was performed by this backend slice.
