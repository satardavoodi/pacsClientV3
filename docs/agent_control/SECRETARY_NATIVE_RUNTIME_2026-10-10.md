# Owner-bound native Secretary runtime

`PacsClient/pacs/workstation_ui/home_ui/secretary_native_runtime.py` provides
`NativeSecretaryRuntime(widget, owner_getter)` and asynchronous
`dispatch(operation, payload)` on the existing qasync GUI loop. It uses the
existing widget, orchestrator, preplan workers, CommandBus, renderer and memory
store. It does not open a GUI, authenticate, launch a provider, create another
brain/store, or deploy a network endpoint.

## Admission and lifecycle

The authenticated bridge supplies `owner_id`, the exact confirmed server user
principal. Its GUI callback `owner_getter` must return the current canonical
`user_session.confirmed_admission(client)['principal']`, or None. Username
equality and phone-provided owner IDs are insufficient. Authentication/renewal
remain off the GUI thread and outside this adapter. Construction requires the
existing native orchestrator/memory to be available before session operations.
One runtime attaches to one widget; it exposes a random `runtime_instance` UUID.
All calls and lifecycle hooks run on the GUI loop. Thread-mismatched dispatch
fails before touching widgets. The connector owns authentication and marshaling.
The existing widget invokes the connector's synchronous, idempotent
`schedule_widget(self)` after either successful orchestrator-ready branch, and
`close_widget(self)` at the start of cleanup. These hooks do not create a second
orchestrator or cancel the local brain; normal widget teardown keeps its existing
ownership. The connector implementation owns role/admission/service attestation
and scheduling on the existing qasync loop.

Logout/disconnect calls `close()`. Admission then fails closed. Active or pending
work becomes `completion_unknown`; close neither cancels side effects nor proves
server drain. In-flight work is never replayed. Pending approval is not converted
into a desktop modal when admission disappears. Teardown/recovery of an orphaned
pending native operation requires the connector/GUI lifecycle owner; no new owner
can adopt it through this facade. No deployment, restart or live acceptance is
implied by these source changes.

## Operations

Every operation includes trusted `owner_id`. Mutations include canonical UUID
`request_id`; all except status/result require the current conversation UUID in
`session_id`. A replay with identical operation/payload returns its receipt;
reusing an ID with different content fails. Runtime receipts are bounded at 256
mutations, then require a controlled runtime lifecycle transition.

| Operation | Input | Result |
| --- | --- | --- |
| status | owner_id | busy, stage, runtime_instance, current session |
| session.list | owner_id | sessions captured by this authenticated runtime |
| session.get | captured session_id | current or read-only historical session and captured turns |
| session.new | session_id, request_id | queued receipt; poll request_id for same-store worker terminal/new session |
| command.submit | session_id, request_id, text, mode, optional language_preference | accepted running request |
| command.result | submit, confirmation or New request_id | actual rendered result or queued/pending/terminal receipt |
| confirmation.answer | session_id, fresh request_id, pending_request_id, confirmed boolean | exact native pending approval or rejection |

Submit supports Act/Ask/Guide; Help Ticket's separate packaging/delivery UI is
explicitly unsupported. Text is bounded to 20,000 characters and credentials
must use the local entry form. Local and mobile submissions share the widget
busy/recording lock. Confirmation keeps that lock until the exact pending command
finishes. Remote clarification text is returned as a failed NEEDS_CLARIFICATION
result; adopting a multi-option clarification is not implemented by this contract.
No remote modal is opened for it. Optional `language_preference` accepts only
`fa` or `en`. The widget passes it through the existing orchestrator and company
execution-repair transport to `remote_planner`, which negotiates server support.
The original current request text remains unchanged. The server-owned shared
resolver prioritizes its explicit target/current language; preference is only
the fallback for mixed or nonlinguistic input. No client translation/provider
call or alternate model/routing policy is introduced.

Only sessions and turns observed by this runtime are exposed, including new
desktop-native inputs and their actual rendered outputs after runtime attachment.
New Session and ten-cycle rollover preserve already captured session metadata
and turns; those sessions become `current=false, read_only=true`. They may be
listed/read, but never resumed or mutated. Legacy global disk history has no
owner/session mapping and is never scanned or adopted. At automatic memory
rollover, only the active request's captured turns move to the actual new
conversation ID; earlier turns keep their original session. Session files remain governed by the separate
[session sources contract](SECRETARY_SESSION_FILES_2026-10-09.md).

Example terminal result (synthetic):

```json
{"ok":true,"runtime_instance":"00000000-0000-0000-0000-000000000001","request_id":"00000000-0000-0000-0000-000000000002","session_id":"00000000-0000-0000-0000-000000000003","state":"succeeded","mode":"ask","text":"Actual rendered answer","response":{"ok":true,"action":"ask","message":"Actual answer","error_code":null}}
```

Pending state is `awaiting_confirmation` with `pending_request_id` equal to the
original submit UUID and `confirmation: {message, action}`. Poll the original
submit UUID after answering, even though the answer has its own idempotency UUID.
Confirmation acceptance returns `running` immediately after reserving the fresh
receipt and exact pending state, then schedules a runtime-owned GUI task. It does
not await the local action within the bounded RPC call. Both original and fresh
confirmation receipts follow actual terminal/cancelled state, and retries never
schedule another execution. `session.new` similarly returns `queued` with the
old current session ID; poll its fresh UUID with command.result until terminal
`session`/`session_id` contains the actual new conversation. The shared busy lock
lasts until the accepted disk/SQLite worker really stops. The root facade retains
the operation lease while polling; transport disconnect/close does not cancel
these runtime-owned tasks. Admission loss yields completion_unknown, not a
fabricated successful completion or replay. Chunk retrieval remains unrelated.
Completed turns have id, role (user/assistant), text, request_id and session_id.
Session metadata includes id/title/mode, memory_number, cycle_count, cycle_limit,
current and read_only. Status reports history_supported=true only for this
runtime's captured projections; resume_supported remains false.

## Private service-transition admission

`admission.hold` and `admission.release` are private native IPC operations, not
public mobile/HTTP administration. Both require the existing attested owner and
canonical UUID `transition_id`. Root service admission invokes transition guards
outside its condition lock; the transport binds the guard to this runtime.

The atomic GUI hold checks recording, pipeline busy/pending state, every native
orchestrator session's pending choices, active runtime/widget execution tasks and
registered worker lifetime. Only proven idle sets the widget input/memory-reset
fence. Known busy refusal returns ok=true, held=false, busy=true without changing
the fence. Same-transition holds are idempotent; another active transition fails
HOLD_CONFLICT. Exact receipts use:

```json
{"ok":true,"runtime_instance":"00000000-0000-0000-0000-000000000001","transition_id":"00000000-0000-0000-0000-000000000004","held":true,"busy":false}
```

Release requires the same active transition, is idempotent after its release and
rejects stale IDs with HOLD_MISMATCH. If work unexpectedly remains busy it retains
the fence and reports held=true, busy=true; this is not idle certification.
Native typed input, voice start, New memory, Files-triggered rollover and new
remote mutations are fenced with an explicit temporary-pause message/error.
Read-only status/history and existing operation-result polls remain available.
No accepted execution, recording or brain task is cancelled to obtain idle.

Close clears only its own fence after proven task/worker/pending idle, otherwise
defers release to the pipeline/task completion hooks. Unexpected transport loss
still poisons the root transition as unknown; a local flag change is not a remote
idle certificate. Actual GUI/process destruction during accepted work is a
separate lifecycle acceptance gate, not covered by transport-disconnect tests.

## Private normal-idle detach proof

`prepare_idle_detach(detach_id)` is synchronous and GUI-thread-only. It accepts
a canonical UUID and returns None for invalid identity, changed/unavailable owner,
foreign thread, closed runtime, conflicting detach ID, or any active/uncertain
recording, pending choice, pipeline/task/worker state. Proven idle atomically sets
the widget's permanent terminal input fence, separate from the temporary service
hold, and returns exactly these six private fields:

```json
{"protocol":1,"detach_id":"00000000-0000-0000-0000-000000000005","runtime_instance":"00000000-0000-0000-0000-000000000001","owner_id":"synthetic-principal","terminal_fence":true,"busy":false}
```

The same detach ID is idempotent while the runtime remains admitted/idle. Reads
can continue, but new local/remote commands, recordings and memory resets are
permanently fenced for that widget. Temporary service-hold release and runtime
close cannot reopen this terminal fence. Old operation receipt replay only reads
its existing result; it never re-executes work.

At cleanup start the widget prepares a fresh detach UUID and passes proof (or
None) to `close_widget(self, idle_detach=proof)` before panel teardown. The transport
validates the strict proof and performs a bounded private detach/ACK handshake;
root admission retires only the exact epoch/runtime with no accepted queued,
running or awaiting-confirmation operation. Preparation alone is not remote
acknowledgment or idle retirement. Busy/forced exit, missing ACK or process loss
remain uncertain; no accepted action is cancelled to manufacture this proof.
Real SCM/native teardown and clinical continuity acceptance remain separate gates.

## Bounded retention and oversized results

Captured history retains at most 64 sessions, 128 complete turns and 192 KiB of
aggregate escaped-JSON UTF-8 bytes (including metadata/IDs, conservatively larger
than unescaped text). Oldest complete turns/sessions are evicted, never silently
truncated or replaced with empty answers. The current schema-bounded session
metadata is retained. This is a transient projection, not another MemoryStore.
Canonical conversation files, native rendered text and the current actual command
result are not rewritten by retention.

Status, session.list and session.get return additive top-level `history_coverage`:

```json
{"scope":"authenticated_runtime","complete":false,"retained_sessions":3,"retained_turns":40,"retained_utf8_bytes":100000,"evicted_sessions":0,"evicted_turns":20,"session_limit":64,"turn_limit":128,"utf8_byte_limit":196608}
```

Coverage describes the whole authenticated runtime's retained projection, not
only the selected session. `complete=false` explicitly marks missing captured
history; it never implies coverage of unowned legacy disk records.

Receipts retain at most 256 mutation identities with hashed idempotency signatures
and a separate 192 KiB aggregate body budget. Old receipt text may expire, but
original execution state and identity survive; replay never re-executes work.
Expired text returns top-level `ok=false, error_code=RESULT_EVICTED` together with
request_id, session_id, runtime_instance and actual execution state. In
particular, completion_unknown remains unknown, never converted to failed/success.

Command results exceeding 384 KiB of escaped JSON return an explicit top-level
error instead of exceeding the 512 KiB RPC frame:

```json
{"ok":false,"error_code":"RESULT_TOO_LARGE","text_bytes":200000,"request_id":"00000000-0000-0000-0000-000000000002","session_id":"00000000-0000-0000-0000-000000000003","runtime_instance":"00000000-0000-0000-0000-000000000001","state":"succeeded"}
```

`text_bytes` is the actual unescaped current answer's UTF-8 byte length. Transport
failure is distinct from execution state. The intact latest answer stays in the
native renderer/current command until superseded; no shortened answer is
presented as complete. These errors use top-level error_code, while ordinary
execution errors can also be in response.error_code. Clients/facade must check
both. Chunk retrieval is not implemented; oversized phone delivery is an explicit
limitation pending a shared Android/iOS paging contract.

## Verification and open gates

The initial six guards failed due to the absent module. The history/language
extension added six further fail-before guards for captured New/rollover
history, desktop render capture, invalid preference, company planning and repair
pass-through. All 18 native guards now pass. Together with existing confirmation,
result-text, async/busy, shared language resolver, remote planner and runtime
contract guards: 81 passed, exit 0 on 2026-10-10. The two changed EchoMind sources
were synchronized selectively using `sync_plugin_mirrors.add_paths`; their
packaged mirror hashes must match before source staging.
The bounded-retention slice added three fail-before guards for turn/session/byte
limits plus three guards for honest Unicode coverage, explicit oversized results
and idempotent receipt eviction. Two additional readiness-hook guards failed
before hook placement; a teardown-order guard verifies connector close precedes
panel teardown without cancelling the local brain. All 27 native guards pass;
the combined focused suite including the connector tests passed 98 tests,
exit 0. Tests use synthetic state only, without live
data, providers or GUI login.
The asynchronous acceptance slice added two fail-before delayed-confirmation/New
guards and rejection/close-state guards. All 31 native guards pass; the combined
focused suite including the current connector guards passes 107 tests, exit 0.
The service hold slice added four fail-before guards and stale-release/delayed
local-task guards. All 37 native guards pass; the current combined focused suite
passes 113 tests, exit 0. It does not exercise actual clinical actions or SCM.
The normal-idle detach slice added seven fail-before proof/fence guards and
foreign-thread/owner/cleanup-forwarding guards. All 47 native guards pass; the
current combined focused suite including connector checks passes 124 tests,
exit 0. No real GUI close, service restart, Razi activation or parity is implied.
Actual native GUI, authenticated IPC/8002 facade, Android and iOS, source parity
and Razi activation remain separate owner-coordinated gates. The Eagle Eye owner
stages reconciled immutable source only after concurrent edits settle.


## Source-only QA binding discovery

On the existing opt-in local TestControl channel, `secretary_runtime_binding`
with empty entities returns only `runtime_instance` and `current_session` from
the already attached, current-owner native GUI runtime. These differ from the
public server epoch runtime_id. Use the returned UUIDs with the original request
UUID in `secretary_terminal_receipt`. No runtime/session is created, no bus action
is executed, and no patient data or owner identity is returned. Closed, wrong
owner/thread, missing state or extra entities return NOT_FOUND. This is not a
public Agent action or authorization bypass. Live Razi acceptance is pending.


## Default Server Home attachment (2026-10-11)

Server Home schedules the existing native attachment after CommandBus readiness,
without a local command or a QA mutator. Existing orchestrator/session state is
preserved. Managed service/human preparation stays on a worker; the pure
orchestrator constructor binds Home on the GUI loop and cold memory initializes
on a worker before native runtime construction. Local entry and memory-label
refresh wait for initialization. Closure, changed owner/login generation or
orchestrator replacement rejects late attachment. Closing during memory prime
does not cancel the database worker; its completion cannot attach a closed runtime.
Native session capture reads only initialized `_memory_store`. Fixed lifecycle
classifications are logged without exception text, credentials or commands.
Razi activation and real Home/mobile acceptance remain separate pending gates.

Review corrections: the initialization fence clears immediately after successful
connector start, while its healthy lifetime loop continues. Server local entry
and label refresh never invoke lazy storage after failed priming; they report
unavailable until a valid initialized store exists. Client behavior is unchanged.
Synthetic guards exercise actual local entry during the healthy connector loop
and reject cold property access after a failed prime.


## Headless unit-test audio isolation (2026-10-11)

The r11 Razi candidate suite reported eight native lifecycle test failures from
PortAudio initialization during UI imports under SSH. Native runtime tests now
install a scoped synthetic sounddevice module before imports, including an
explicit guard that rejects hardware access. Cached UI references are patched
for each native test. These tests never qualify microphone behavior; no runtime
audio code or permissions change. Remote rerun and actual source GUI acceptance
remain required and separate from local synthetic results.

Test teardown restores preexisting UI audio references and evicts newly imported
UI namespace/cache bindings when the first import happened inside isolation.
Preexisting exported class bindings are restored. Cleanup never imports real
PortAudio on SSH. Two deterministic guards cover preexisting and first-import
cases; the complete local focused suite is 105 passed, six SWIG warnings.


## Safe attachment failure stages (2026-10-11)

The actual r12 GUI reported attachment_failed; this alone did not identify the
cause. Independent read-only service/config/client preflight passed, but this
does not prove the GUI human session or native attachment. No root cause is yet
asserted. The next candidate records fixed stage/category enums for admission
substeps, runtime imports, orchestrator construction, memory prime, generation,
native runtime construction/capture, connector construction/start and liveness.
Exception messages, tracebacks, identities, paths and command text are excluded.
The source-only local TestControl `secretary_lifecycle` with empty entities reads
only an already existing attachment: {stage, category, closed}. It creates no
object, executes no action and does not retry authentication. Unknown/extra input
or missing attachment returns NOT_FOUND. Production Agent APIs are unchanged.
Three initial guards failed before diagnostics implementation. Real failure
identification still requires the reviewed immutable candidate and native GUI.


## Upstream console to ordinary human admission (2026-10-11)

Actual r13 lifecycle diagnostics confirmed human_session/authentication. Server
console login deliberately did not publish ordinary human context, while native
attachment required it. Successful current upstream PACS/Reception console login
now publishes only bounded memory-only username/password context with the exact
verified provider and subject. Native attachment still performs the ordinary
/v1/auth/session exchange on its worker. The returned provider/subject must match
before caching; the server-returned canonical principal remains authoritative.
Console tokens are never AI tokens. Local provisioned superadmin stays console
only. Public mobile APIs and per-request permissions are unchanged.

A unique attempt identifier and identity generation reject stale completion.
New attempts are rejected while the existing worker is busy, so its failure signal
cannot clear a newer attempt. Transient context is dropped on completion/failure;
ordinary login context remains memory-only until identity invalidation. An old or
foreign console invalidation cannot revoke newer context. Only the matching
accepted console session/current generation clears its published human context.
No explicit GUI logout flow is newly implemented or claimed; invalidation-hook
qualification is separate from native logout/GUI acceptance. Process exit clears
process memory. Existing unconstrained Client login compatibility is preserved.


## Public permission booleans (2026-10-11)

The public user objects in /v1/auth/session and /v1/auth/me now project enabled,
echomind, imaging, crm and secretary as JSON booleans. SQLite integer storage
previously reached the wire unchanged, so strict mobile boolean checks rejected
a valid grant. Only canonical integer 1 or boolean true projects as true; strings,
other integers and malformed values project as false. Identity fields and modules
are preserved. AccessStore and all authentication, revalidation and grant
enforcement remain unchanged. Fresh /auth/me reads reflect revoked permissions.
Eight regression cases failed before the fix. Automated checks are recorded in
the scoped receipt; actual Android/iOS acceptance and Razi activation are pending.
This source change applies to Server response serialization only and introduces
no new client credential route, dependency, flag or payload module.
