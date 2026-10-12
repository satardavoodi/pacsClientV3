# Native heartbeat diagnostic evidence

R18 acknowledged native pipe admission and later reported `receive/filesystem`.
`ConnectionError` is an `OSError`, so this category did not establish a filesystem
fault. Existing logs did not retain heartbeat failure stages or last-frame timing.
The original disconnection cause remains unproven.

This diagnostic-only delta preserves authority verification, RPC budgets, locks,
dispatch, uncertainty, poisoning, close behavior and the absence of automatic retry.
Channel failures retain a fixed reason distinguishing local closure, read/write
deadline and peer disconnection. Existing source Test Control lifecycle evidence
adds this reason; no mobile response or public API is added.

The existing private `transport_diagnostics` receipt optionally includes
`native_pipe`. Legacy receipts remain valid. The extension has exactly `stage`,
`reason`, `calls`, `succeeded`, `elapsed_ms` and `last_success_age_ms`. Stages and
reasons are allowlisted; counters and elapsed milliseconds are saturated nonnegative
integers. Zero success age before any success is not evidence of a successful call.
The entire maximum-count private receipt remains below its existing 4096-byte cap.

`calls` includes accepted admission observations, RPC attempts, and subsequent host
validation failures. It is diagnostic activity, not user request accounting. The
descriptor follows the latest begun observation. An earlier overlapping RPC can
increase the success counter and update success age but cannot overwrite a newer
failure stage, reason or duration. No per-request history or unbounded map is kept.
Listener waiting preserves the previous failure until a fresh accepted admission.

The server heartbeat still verifies the existing human session every five seconds
before sending status. These checks do not consume the login attempts bucket;
they share four concurrent upstream authentication slots with other verification.
An initial ACK does not prove later identity validity or heartbeat completion.

Synthetic guards cover distinct channel causes, authority denial, concurrent
completion, lock failure without changed channel cleanup, repeated successful status
calls, strict extension privacy and worst-case wire length. They do not establish
live Android/iOS acceptance or diagnose the original R18 failure. Source activation,
hash parity, human launch/login and fresh mobile acceptance remain coordinator gates.
