# Native Secretary HTTP integration

Status: source integration in progress; not activated or accepted on Razi.

The ordinary `X-Eagle-User-Session` authority and local Secretary grant protect
every `/v1/secretary/remote/` route. No device pairing is required for this Server
target. Mutating requests additionally require the Server license. The server
derives the principal from verified authority; phone bodies cannot select an owner.

The public `secretary_remote` capability declares protocol 1, native Windows
execution and `/v1/secretary/remote` as the base path. Status distinguishes a
supported facade from an available, same-human native runtime. No second planner,
memory store or legacy fallback is created when the GUI is absent.

GET routes provide status, sessions, session detail and request-ID operation
lookup. POST sessions creates a native session; POST operations accepts text or
confirmation. Strict facade validation rejects unknown fields and noncanonical
UUIDs. Accepted work retains its admission lease beyond HTTP 202 until a native
terminal receipt. Disconnect marks completion unknown and prevents certified idle;
the server never replays a mutation automatically.

Text and confirmation operation session identity remains the accepted identity
through native memory rollover. A changed native session is reported separately
in output.current_session_id. New-session results expose their new session.

Captured history is limited to the authenticated native runtime. Whole-turn
eviction is reported by additive history_coverage metadata. RESULT_TOO_LARGE and
RESULT_EVICTED preserve actual execution state and provide an explicit output
error rather than a fabricated or truncated answer. Chunk retrieval is not part
of this protocol version.

The private Windows pipe starts only when the actual service/request loop starts,
not when tests merely construct an HTTP server. It authenticates the existing
GUI human session and rechecks the Secretary grant. GUI attachment must attest
the exact official LocalService process before transmitting its session token.
Shutdown closes remote admission without cancelling the local orchestrator.

Verification gates remain separate: facade/HTTP/pipe/native automated guards,
official SCM Session0 attestation, signed-in GUI attachment, Android and iOS native
UI behavior, real server/provider response, immutable Developer hash parity and
controlled activation. Unit results alone do not satisfy live acceptance.

Normal idle widget retirement uses a private proof with protocol, detach_id,
runtime_instance, owner_id, terminal_fence and busy fields. The GUI must atomically
establish a permanent input fence before producing it. The host accepts only the
same authenticated binding and no queued, running or awaiting-confirmation work.
A lost, stale or malformed proof remains completion uncertainty; existing
uncertainty is never cleared. Forced process exit has no graceful guarantee.

The facade guards reproduced two failures before the idle-retirement API existed;
all 11 facade guards now pass. The preceding integrated transport/admission/install
selection passed 96 tests. Updated transport/native GUI integration and live
acceptance remain pending; these counts are source checks, not clinical activation.
