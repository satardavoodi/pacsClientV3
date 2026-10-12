# Private admission and cooperative transition contract

Status: inactive canonical source, synthetic qualification only. No active Razi
process, executing source, SCM registration or deployment configuration was changed.

## First-transition bootstrap remains blocked

The active `20261010-ordinary-human-r2` process does not obtain trustworthy drain
counters merely because these files exist in another snapshot. New counters cover
only accepted work in the new process since its own startup. They cannot certify
old model jobs, old text requests, old Secretary work or the old CRM worker idle.
The Eagle owner must independently resolve the old-active bootstrap and complete
source reconciliation before any first transition. Port availability, a capability
response, copied files, queue files or these synthetic tests are not that proof.

The old service child treated any stdin line as a stop request. Accordingly, the
new parent requires the private `EAGLE_EYE_ADMISSION_READY_V1` handshake before
writing a transition command. Do not send a JSON probe to the old active child.
No handshake means refusal before writing, not a fallback to the old stop path.

## Process-local accounting

`admission.py::Admission` serializes admission and transition state under one
condition lock. The snapshot contains only state, aggregate accepted/completed
counts, inflight count and a sticky completion-uncertain flag; no patient, request,
principal, credential or payload data appears in it.

The server handler counts every accepted HTTP operation through the full response
or failure path, including synchronous EchoMind, Secretary, CRM, speech and lumbar
vision. HTTP authentication and read operations are counted too. Once quiesced,
new requests receive 503 `SERVER_QUIESCED`; no privileged HTTP mutation endpoint
was added. A bounded unread body is consumed before refusal where possible.

`Jobs.submit` additionally reserves a model lease before scheduling. HTTP 202 and
durable terminal state are not the completion boundary: the Future completion
callback releases the lease after worker cleanup. Scheduling failure releases its
reservation. Duplicate known jobs create no new model lease. Existing job identity,
permissions, module/license checks and execution cancellation contracts are retained.

CRM host requests are synchronous through their worker response or owned cleanup.
An unexpected exception escaping CRM processing marks completion uncertain. Known
`RequestFailed` results follow the host's completed cleanup contract. Unknown model
cleanup and unexpected Future completion failures also mark uncertainty. Uncertainty
is sticky and blocks cooperative close even when inflight reaches zero. It is not
silently cleared by an administrator command; recovery requires separate ownership
inspection. This does not resolve the existing CRM worker startup/read timeout.

| State | New admission | Transition behavior |
|---|---|---|
| open | Allowed | One drain can start |
| draining | Rejected | Wait for accepted work within the monotonic budget |
| quiesced | Rejected | Zero known work; resume or commit |
| closed | Rejected | Commit made; resources may now close |

Budgets are finite numbers greater than zero and at most 600 seconds. Boolean,
NaN, infinity and out-of-range budgets are rejected before changing admission.
Drain expiration or uncertain completion aborts the transition and restores open
admission without cancelling work, closing resources or killing a process. Concurrent
drain/resume cannot race the waiting operation. A close callback is invoked only
after an atomic quiesced/zero/certain check; callback failure is not a successful
close and cannot reopen the committed process.

## Private owning-parent control

The existing anonymous parent/child stdin/stdout pipes carry a bounded, correlated
protocol. They are not a public socket, file-polled command channel or new HTTP API.
Only the parent that owns the child has these pipe handles. No additional external
administrator CLI or remote command surface is installed by this change.

The owning process calls `Supervisor.safe_transition(timeout)`. After both listener
and admission handshakes, it sends exactly:

```json
{"protocol":1,"operation":"stop_when_idle","request_id":"00000000000000000000000000000001","timeout":20}
```

The child strictly validates the schema, starts the drain and emits only a correlated
aggregate receipt prefixed `EAGLE_EYE_TRANSITION_V1 `. A busy drain returns aborted
with admission open; the parent returns false and leaves the child running. A zero
drain commits admission closed and signals the bounded listener loop to close the
server and owned resources. The parent returns true only after a matching zero/certain
receipt AND the owned child exits with code zero within its close budget.

A missing acknowledgement or incomplete close is indeterminate: report it and
inspect the owned process. Never reinterpret it as a successful drain, automatically
retry the transition, call emergency stop, or kill the child. Once commit happened,
an acknowledgement/close timeout cannot safely promise resume; only a drain-budget
abort explicitly promises resumed admission.

The existing SCM stop, EOF/parent loss, Supervisor.close, desktop-host close and
standalone shutdown retain emergency/legacy semantics. They may cancel or terminate
owned work and are NOT the safe transition API. The existing emergency service tests
are retained; no claim is made that replacing source retrofits an old SCM instance.
Operator integration into a reconciled owning service remains a separate live gate.

## Evidence and pending acceptance

New guards: `tests/code/ai_imaging/test_server_admission_drain.py`. The initial ten
contract guards failed before implementation because no admission contract existed.
Synthetic tests now cover overlapping model/text/Secretary/CRM work, real loopback
HTTP refusals and responses, async model completion after submission, private owned
subprocess busy-abort/resume then zero-exit, invalid/unsupported private commands,
old-child handshake refusal, uncertain cleanup, acknowledgement and close timeout,
and preservation of existing authentication/license/lumbar/language behavior.

Receipt: `generated-files/eagle-eye/safe-transition-20261010.json`. It records the
exact scoped hashes and test results. This source change supersedes the historical
language receipt's `server.py` hash; its frozen helper and Secretary policy are
unchanged. Earlier language parity receipts must not be reused as complete parity.

Pending gates: trustworthy old-active drain bootstrap; full immutable local/Razi
Developer source and payload reconciliation; review of every independent owner
delta; real CRM worker acceptance; approved local administrator integration and
live concurrent workload acceptance; safe activation only after those gates.
No provider calls, production activation, restart, package build or release occurred.
