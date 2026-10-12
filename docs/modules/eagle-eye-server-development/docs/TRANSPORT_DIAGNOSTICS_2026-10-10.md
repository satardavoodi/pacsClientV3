# Private transport diagnostics

The source candidate maintains fixed transport counters in each HumanHTTPServer
instance. Counters have twelve fixed reason labels and four fixed route classes:
other, auth_session, auth_me and public_capabilities. Each integer saturates at
2**63 - 1. Snapshots copy the rows under a lock and include a random instance UUID.
They contain no peer addresses, usernames, tokens, request text, exception messages
or arbitrary paths. They are evidence of server activity, not client receipt.

The owning service supervisor can call transport_diagnostics(timeout=2), with a
maximum five-second budget. It uses the existing private parent-child stdin/stdout
pipes and a separate bounded diagnostic queue. Its request has exactly protocol=1,
operation=transport_diagnostics and a 32-character lowercase hexadecimal request_id.
The child does not change admission, drain, stop or restart for this operation.
Replies use EAGLE_EYE_TRANSPORT_DIAGNOSTICS_V1 and at most 4096 UTF-8 bytes. The parent
rejects extra keys, unknown labels, invalid counts and oversized/incomplete frames.
Transition requests retain their separate parser, 512-byte budget and queue.
There is no public diagnostic HTTP endpoint.

Preface counters distinguish connection capacity, first-byte timeout/read failure,
peer close, unavailable TLS, failed TLS handshake and invalid preface. The handler
counts completed JSON writes and write failures using the fixed route classes.
Timeouts escaping dispatch and unexpected escaping handler failures are counted;
exceptions already converted into workflow-specific HTTP responses are not thereby
reclassified as transport failures. Artifact streaming is not included in JSON
response_completed. HTTP errors can still be complete transport responses.

Synthetic guards cover HTTP and TLS login/capabilities/me JSON responses, malformed
preface and capacity refusal over real loopback sockets, strict private control
validation, oversized frames, correlation, concurrent updates, saturation and
missing acknowledgements without lifecycle mutation. Clinical Android acceptance
and active deployment are separate and remain pending for this source candidate.

## Android second-exchange compatibility guard

A saved-identity Android diagnostic established a successful fresh-pool login
(HTTP 200, HTTP/1.0, 206 ms), followed by an unexpected end on the next identity
request (14 ms). No provider request was made. This narrows the failure to the
second HTTP exchange; it does not prove a verifier or provider failure.

All JSON and ZIP responses now explicitly advertise Connection: close and set
the handler closing state. Two HTTP/HTTPS pool-sequence guards failed before the
header change and pass afterward. The ordinary/native HTTP selection passes 17
tests. The requests-based pool guard validates framing and sequential authority;
actual Android/OkHttp acceptance after controlled activation remains required.
No TLS trust, human authority or permissions were weakened.


## Mobile acceptance availability update

On 2026-10-10 the owner confirmed that the authoritative Mac is unavailable.
Final live iOS acceptance is blocked by host availability, not a passed or failed
server/provider test. Retain the existing iOS source/build receipts separately;
they do not establish fresh device acceptance of the pending server revision.
Do not create another iOS checkout or weaken TLS/device trust to bypass this gate.
Resume the same shared Android/iOS contract on the authoritative Mac when it is
available. Android, immutable Razi staging and nonclinical A100 preparation may
continue independently. Shared mobile completion remains open until both platform
acceptance receipts are recorded.


## Mobile availability restored

Later on 2026-10-10 the owner confirmed that iOS is available again, and scoped
Codex messaging to the authoritative Mac succeeded. The iPhone simulator is
reported ready; physical-device and external-route acceptance remain separate.
The previous availability blocker is superseded, not converted into a test pass.
Resume the three-route Secretary matrix in SECRETARY_MOBILE_ACCEPTANCE_2026-10-10.md
only after the exact candidate and dedicated native runtime/session are ready.
