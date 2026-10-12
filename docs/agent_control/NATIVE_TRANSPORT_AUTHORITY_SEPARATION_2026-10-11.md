# Native transport and authority separation

Observation 04 retained a service AUTH upstream_unavailable failure (5003 ms),
followed by the GUI receiving peer_disconnected and losing its binding. The
service child remained unchanged. This establishes the disconnect chain; it does
not identify the underlying PACS/reception network fault or an LLM failure.

Private transport.ping validates the existing opaque session, device binding,
monotonic expiry, current enabled state and Secretary grant locally. Its GUI
handler verifies GUI-thread and owner identity and returns only runtime identity;
it never reads patient/session data, dispatches commands or certifies idleness.
Admission still requires full upstream verification. Every business status,
session, command and transition hold/release RPC retains full upstream identity
and local permission checks. Idle-detach remains an explicit terminal fence proof.

Only typed AUTH failures (429 UPSTREAM_AUTH_BUSY or 503
UPSTREAM_IDENTITY_UNAVAILABLE), before any frame is sent and within the RPC
budget, preserve the synchronized pipe while rejecting that call. There is no
request retry, replay, implicit reconnect, cached business permission or provider
fallback. A later explicit business call must verify upstream again. Denied,
expired, logged-out, disabled, grant-revoked or changed ownership closes; wire,
correlation and post-send failures retain conservative completion uncertainty.
A known-unsent result poll cannot prove its earlier command was unsent: accepted
submission followed by failed polling remains completion_unknown and uncertain.

Upstream revocation is discovered on the next full business check; transport ping
alone cannot establish current upstream permission. Local expiry remains enforced.
The existing captured-token/confirmed-admission renewal gap near one hour is
separate and unresolved by this bounded-outage change. No long-session acceptance
or live deployment is claimed. Synthetic tests use no clinical databases/provider.
