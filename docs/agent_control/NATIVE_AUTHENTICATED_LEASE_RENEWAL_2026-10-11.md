# Native Secretary authenticated lease renewal

The native Server Secretary attachment keeps the same opaque human token while
renewing its authenticated lease. This is an optional Server capability; Android
and iOS login, pairing, transport and business request contracts are unchanged.
Mobile and live native acceptance remain separate pending gates.

`POST /v1/auth/session/refresh` accepts exactly `{}` with the existing device
Bearer and `X-Eagle-User-Session` headers. It requires an unexpired, matching
device session, current enabled/Secretary grants and fresh upstream verification
of the exact bound provider identity. After verification it checks that the same
session record is still live and checks local grants again before setting its
expiry to the current monotonic time plus the unchanged 3,600-second lease.
Logout, replacement, expiry, identity changes or revoked permissions cannot
resurrect or extend a lease. Upstream failure does not extend expiry. Rolling
renewal is authenticated each time; it does not establish an absolute maximum
login duration or make an expired upstream identity valid.

The attachment checks renewal every 30 seconds, beginning before the existing
client admission deadline has fewer than 300 seconds remaining. Network work
runs through `asyncio.to_thread`. Existing exchange serialization allows one
renewal at a time, and transient failures allow another attempt no sooner than
60 seconds later. The current cache remains valid only until its original
deadline unless a valid same-token, same-principal, same-generation response is
accepted. The refreshed client deadline is bounded by request start plus 3,595
seconds, so response latency cannot inflate the server lease. No password or
provider credential extraction, operational replay, reconnect or pipe rekey is
introduced. Late denied responses cannot clear a newer human login.
Captured-refresh connection failures use a fixed transient 503 classification;
malformed responses and other invariant failures remain fail closed. Existing
network error behavior for all other client routes is unchanged.

Closing an attachment prevents further renewal attempts and client cache commits.
A request already in flight may finish its authorized server renewal; cancelling
a Python worker cannot undo accepted server work. Local logout and generation
changes still revoke or invalidate the human context. Definitive denial or expiry
remains fail closed. Long upstream outages and expired upstream tokens eventually
require legitimate human authentication; this feature does not bypass them.

Synthetic guards in `tests/code/ai_imaging/test_native_session_renewal.py` cover
rolling leases beyond two hours, device/expiry rejection before provider calls,
logout/replacement/permission/identity races, transient failure without extension,
single-flight and bounded retries, cache generation and lifecycle races, the
optional HTTP route, client route restriction, response-latency bounds and
off-GUI scheduling. Fifteen initial guards failed before implementation because
the renewal APIs were absent. Local/Razi immutable-source parity, fresh live
binding and mobile acceptance are pending; no release or deployment is implied.
