# Protected native diagnostic collection

The existing supervisor child supports `transport_diagnostics`, but its injected
`ServiceControlHost.diagnostics` callback was not reachable through the private
administrator control exchange. The read-only `transport_diagnostics` operation
now uses that existing protected exchange. No HTTP/mobile route is added.

The client helper is `service_control.transport_diagnostics(config_path,
expected_identity, deadline_monotonic)`. The budget is at most five seconds.
Requests retain the existing ACL, reviewed source/config/runtime hashes, exact SCM
PID and creation identity, correlation UUID, deadline and replay/capacity checks.
The existing custom SCM control 128 only wakes the serialized private worker; it
does not send STOP, start a service, drain, cancel work or request inference.

The diagnostic branch never invokes `safe_transition`. It calls only the already
injected diagnostic callback, validates the strict legacy-compatible transport
snapshot, checks the deadline again, and writes a bounded private receipt.
Success is `observed/DIAGNOSTICS_READY`; failure is the fixed
`refused/DIAGNOSTICS_UNAVAILABLE` with no raw exception or snapshot. The client
revalidates correlation, identity and snapshot and attests the service again.
Busy or missing responses time out without recovery. Existing stop request and
receipt fields, client code and custom control sender remain unchanged.

The callback is cooperatively budgeted, not forcibly cancelled. A late callback
cannot publish a ready receipt. Host serialization and the supervisor's private
control lock exclude simultaneous diagnostic and drain execution. Request-file
overwrite cannot certify another caller: UUID correlation fails closed.

An additional diagnostic attribution check follows authority verification before
the send stage. The actual send retains its original remaining-budget check.
This labels slow authority exhaustion as auth/deadline, without claiming to bound
the synchronous authority call or changing authentication/heartbeat policy.

Synthetic tests exercise valid read-only exchange, forged identities/receipts,
replay, deadlines, busy worker, malformed/private snapshot data, callback failure,
and unchanged stop behavior. Causal-matrix tests separately reproduce authority
delay, transient denial, healthy heartbeat and GUI dispatch stalls. These checks
do not establish the cause of the original R18 disconnection. One coordinated
observability launch and subsequent live mobile acceptance remain pending.


Offline acceptance correction: protocol-01 retained 627 passed and one failed
synthetic guard. Its 50 ms wall-clock request expired before host admission,
so zero receipts did not establish callback behavior. The replacement stages
a valid private request, advances only an isolated host clock inside the
callback, and proves a correlated unavailable receipt without transition.
Runtime bytes and service policies are unchanged. The failed candidate and
its XML remain preserved; protocol-01b receives a new immutable QA receipt.
