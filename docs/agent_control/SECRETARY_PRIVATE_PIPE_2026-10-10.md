# Native Secretary private Windows transport

The service and existing GUI live in different Windows sessions. The private
`secretary_pipe.py` transport joins their existing Secretary runtime with bounded
UTF-8 JSON frames, never Python object deserialization. The server-facing facade
owns human-scoped HTTP receipts; this transport owns no planner or memory store.

## Service integration

Construct `NativePipeHost(native_remote, authenticate_session)` and call `start()`
after the service authority and facade are ready. The authentication callback
must validate the existing Eagle human session and Secretary permission, then
return its exact canonical principal. It must have a bounded network deadline.
It runs on a transport worker, and is checked for each RPC plus a five-second
heartbeat. Authentication failures close the channel and detach the runtime.
Call `close()` during service teardown. Startup errors must leave native Secretary
explicitly unavailable rather than substitute a separate brain or legacy route.

The endpoint is fixed to `\\.\pipe\AIPacs.EagleEye.Secretary.v1`. Windows rejects
remote clients. Its protected DACL admits System, administrators, LocalService
and local interactive users; it grants no anonymous or Everyone access. The
first-instance flag prevents an existing endpoint from being silently adopted.
Pipe admission alone is insufficient: the ordinary Eagle user session and module
grant are always required. No public GUI registration endpoint is introduced.

## Existing GUI integration

Create `NativePipeConnector(runtime, token_getter, loop, verify_server)` on the
existing running qasync loop with its existing `NativeSecretaryRuntime`.
`start()` moves pipe I/O and session getters to a daemon worker. The token getter
must be worker-safe and return only the already established Eagle session token.
The mandatory `verify_server(pid)` callback must attest that the pipe endpoint
belongs to the official running Eagle service process tree before any token is
transmitted. A local process name or username comparison is insufficient.
Anonymous security QoS prevents the pipe server from impersonating the GUI user.

All native operations use `asyncio.run_coroutine_threadsafe` to dispatch on the
same GUI loop. Calls are serialized and correlated by canonical UUID. Frames are
limited to 512 KiB; non-finite numbers, duplicate members and non-object JSON are
rejected. The transport has a 15-second RPC deadline, bounded lock admission,
and no connector reconnect, mutation retry, cancellation or replay. The service
listener can admit a fresh explicit GUI connection after disconnect; an invalid
local hello does not permanently disable admission. A dispatched coroutine
may already have side effects; channel loss closes admission and leaves the
facade to report completion uncertainty. Connector close is nonblocking; its
owner closes the native adapter on the GUI loop, including logout/widget cleanup.

## Verification and limits

Six initial guards failed to collect before the transport module existed.
Sixteen focused transport guards pass on Windows after implementation, including real local
byte-pipe JSON exchange, actual server PID lookup and rejected server attestation
before transmitting a hello, and admission after a rejected hello. Tests use unique synthetic pipe names and never
bind the production endpoint. No patient information, provider request or real
session credential is involved.

Official SCM process attestation, lifecycle wiring, service-to-interactive-session
ACL acceptance, GUI dispatch acceptance, HTTP and mobile end-to-end checks are
separate integration gates. No Razi deployment or activation is performed here.
The transport itself does not claim mobile language propagation or historical
session resume. Its callbacks must never log tokens, native text or private error details.

## GUI lifecycle and official process attestation helper

`secretary_native_connector.py` provides `schedule_widget(widget)` and
`close_widget(widget)`. The existing widget calls the first after its own
orchestrator is available, and the second during cleanup/logout on the GUI loop.
The helper prepares the canonical managed Server configuration and existing Eagle
human session on a worker, then constructs only the remote adapter on the GUI
loop. A memory-only admission monitor closes remote access on identity expiry,
logout or pipe worker exit. It does not stop, replace or cancel the local native
orchestrator. After disconnect, a fresh explicit widget lifecycle is required;
pending remote work is not adopted by another owner.

Before transmitting its session token, the connector verifies the service's exact
canonical registered command and LocalService account, RUNNING SCM PID, exact
supervisor and listener executable/argument vectors, bounded exact launcher ancestry,
LocalService process token SID `S-1-5-19`, creation ordering and a stable repeated
SCM snapshot. Cross-session process access denial fails closed. Process names
are never trust anchors. Frozen packages retain the canonical current executable
selection. Developer mode uses the protected reviewed target below, so the GUI
and service may use distinct reviewed Python environments while sharing the exact
source revision. This helper does not trust an arbitrary SCM ImagePath merely
because it is registered.

Fourteen synthetic helper guards pass, alongside the sixteen transport guards (30 total,
exit 0). They cover exact process identity, wrong executable/account/parent,
PID transition, process access denial, Client exclusion, remote-only teardown and
worker preparation followed by GUI-loop adapter lifecycle. Five initial helper
guards failed to collect before the module existed. Real SCM/Session0 access and
native GUI/mobile workflow acceptance remain separate pending gates.

## Protected Developer service selection

Read-only Razi inspection found the official GUI `.venv` junction and the service's
CRM-restoration runtime differ. Windows also launches a venv redirector between
the SCM supervisor and actual listener: the redirector and base Python retain the
same exact `service_host` argument vector. A same-interpreter or immediate-parent
assumption would reject the legitimate service. Developer attestation therefore
permits at most two ancestry edges, each with the exact listener command,
reviewed runtime/base executable, LocalService SID and creation ordering.
Any unrelated executable, changed arguments, extra ancestor or SCM transition is
rejected.

The owner provisions `native-service-target.json` beside the private Server
configuration only after selecting a reviewed immutable source revision. It is
not copied from SCM blindly or shipped with host-specific paths. Fields are:

```json
{
  "schema": 1,
  "source": "<reviewed absolute source root>",
  "config": "<private absolute Server configuration>",
  "runtime_executable": "<reviewed service venv launcher>",
  "runtime_sha256": "<lowercase SHA256>",
  "base_executable": "<reviewed actual base Python executable>",
  "base_sha256": "<lowercase SHA256>",
  "service_entry_sha256": "<reviewed source tools/eagle_eye/windows_service.py SHA256>"
}
```

Paths must use the exact canonical Windows argument spelling selected in the
reviewed service command. Manifest reads are bounded to 16 KiB. The file and its
private parent must be owned by System or Administrators, writable only by those
principals, and readable by LocalService; ancestor ownership and replacement
rights must remain protected. Unknown ACL structures fail closed. Runtime, base
and service-entry hashes and exact source/config binding are rechecked before
service process attestation. Missing manifests, altered files, insufficient GUI
process-query rights or inaccessible private settings leave native remote access
unavailable. This does not authorize elevating the GUI or weakening ACLs.

No manifest or ACL was changed on Razi by this implementation. Provisioning and
cross-session qualification remain owner-controlled integration gates.

The generated `generated-files/eagle-eye/native-secretary-20261010/`
`stage-native-service-target.ps1` is a reviewed preparation tool, not an activation
path. Its default mode only validates supplied reviewed hashes and prints a plan.
Explicit `-Stage` writes a new named pending file, applies the existing private
System/Admin-full and LocalService-read policy to that file only, validates its
parents and candidate source through `read_source_target(..., target_path=...)`,
and emits a new staged-only receipt. It neither changes parent ACLs nor overwrites
`native-service-target.json`, changes SCM, restarts a service or launches a GUI.
A protected parent check failure remains a blocking receipt, not permission to
loosen inherited rights. The owner publishes the reviewed staged file only during
the separately controlled idle activation after source and runtime selection.

The script requires a Windows administrator to stage protected files. PACS or
Reception admin is an application role and does not imply Windows administrator
or sufficient cross-session process-query/token-read access. GUI acceptance must
be recorded for the actual Windows account separately from its PACS permissions.
Do not elevate ordinary workflows or relax attestation to hide AccessDenied.
Windows ACL projection filters INHERIT_ONLY ACEs before the existing pure trust
policy, since those ACEs do not apply to the inspected object. They also cannot
satisfy the LocalService read requirement on the target leaf. Effective untrusted
writes/delete-child permissions and privileged-owner requirements are unchanged.
The exact OS-resolved TrustedInstaller SID is accepted only for higher-ancestor
replacement policy. Targets and immediate parents retain System/Administrators
ownership requirements; arbitrary service SIDs are never accepted. OS lookup
mismatch fails closed, and no ancestor ACL is modified.
PowerShell syntax was checked locally; provisioning was not executed on Razi.

## Private native idle fence

The attached pipe host registers `NativeTransitionGuard` with the service admission
gate before acknowledging GUI attachment. The handshake holds the RPC lock until
the hello acknowledgment is sent, so a concurrent drain cannot overtake it with a
different frame. A handshake admission lease tracks this setup.

After admission enters draining, its callback sends private `admission.hold` with
trusted owner and a fresh canonical `transition_id`. The existing GUI runtime must
atomically refuse if native work, recording or approval is busy; otherwise it
blocks all new local and remote Secretary input. The exact receipt includes
`ok`, `runtime_instance`, `transition_id`, boolean `held` and boolean `busy`.
Known busy refusal aborts without cancelling work or poisoning completion.
Unknown/malformed/lost hold or release evidence poisons the gate and prevents a
certified restart. `admission.release` uses the same transition identity after
abort/resume; a stale identity is insufficient proof.

Hold callbacks receive the remaining drain deadline; the pipe RPC budget covers
lock admission, send and receive together. Its human-authority callback must also
be bounded. An authenticated GUI disconnect loses proof of possible local work
and poisons admission unless the gate was already closed by a certified commit.
The guard is then unregistered; it cannot disappear silently during a drain.
Neither callback kills a GUI process or cancels accepted native side effects.

Known idle widget shutdown has one authenticated exception to disconnect poison.
The native GUI first atomically sets a permanent terminal-input fence and produces
an exact six-field proof: protocol 1, canonical detach UUID, runtime UUID,
canonical owner, terminal_fence=true and busy=false. Only that already authenticated
runtime can supply it. `close_widget(widget, idle_detach=proof)` preserves the first
close request; repeated task-finally cleanup cannot downgrade it to abrupt loss.
The connector keeps only this immutable proof, rejects all new dispatch with
`NATIVE_RUNTIME_DETACHING`, and returns the proof on its next authenticated status
heartbeat without accessing destroyed GUI objects. A 15-second timer bounds this
closing observation. No mutation or authentication replay is introduced.

The service validates exact ownership/runtime and asks the facade to atomically
retire that exact binding only if no queued, running or pending-approval receipt
exists. Then it removes the native guard and closes the channel without adding
new uncertainty. Existing poisoned state is never cleared. Missing, stale,
malformed, raced, revoked or lost proof remains completion uncertainty. Immediate
whole-process exit before the service observes the proof is not graceful evidence.
Normal cleanup during accepted work cannot use this exception.

Tests include actual Windows pipe idle retirement followed by successful service
drain/resume, proof rejection, cached proof dispatch without GUI access, and
idempotent helper teardown. Real native GUI shutdown and clinical acceptance
remain separate pending gates.

Two initial transport-fence guards failed before the guard class existed; three
guards now cover exact hold/release, known busy refusal, malformed proof and stale
release identity. Admission implementation and the native runtime/local-input
fence are separate coordinated components; their integrated and live acceptance
must pass before any activation claim.
