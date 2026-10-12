# Legacy bootstrap admission fence

Date: 2026-10-10

## Purpose

The active Razi Eagle Eye revision predates process-local admission counters. A
new candidate can protect later transitions, but its counters cannot prove that
work accepted by the old process has completed. The bootstrap fence therefore
uses the old revision's existing invariant: every protected request re-reads the
current Eagle Eye human grant through `UserAuthority.verify()`.

`tools/eagle_eye/legacy_admission_fence.py` provides the narrow reversible
controller used around the first transition. It does not stop SCM, select a
revision, inspect clinical data, infer idle state, or expose a remote
administration endpoint.

## Contract

1. Snapshot the exact grants of every currently enabled Eagle Eye human to an
   absolute private crash-recovery file. On Windows the payload is protected by
   DPAPI for the controlling account. No username, provider credential, session
   token, prompt, image or clinical record is stored.
2. In one SQLite write transaction, compare the expected grants and set only
   `enabled=false`. The tool retains all feature/module grants for exact restore.
3. Recheck that no Eagle Eye user is enabled during every drain observation.
   Concurrent grant administration is treated as drift and aborts the
   transition.
4. Require a trusted host observer to report zero active HTTP handlers, jobs and
   sockets for a bounded stable interval. Any uncertain completion, timeout or
   observer failure blocks the transition.
5. Invoke the caller-owned transition only after the stable-idle proof. Restore
   the exact grants after success or failure. A separate recovery function uses
   the private snapshot if the controller process was interrupted.

The observer must cover work already admitted immediately before the last grant
was disabled. Process existence, an HTTP health response, absence of a new
connection or an empty model queue alone is not sufficient evidence.

## Trusted aggregate observer

`tools/eagle_eye/legacy_activity_observer.py` supplies the fail-closed aggregate
observer used by the fence. The concrete adapter requires explicit absolute
paths and an explicit service process ID; none are emitted. It verifies:

- the exact active release ID and deployment-manifest SHA-256;
- that the service command or working directory belongs to the selected source;
- the required read-only user-access schema;
- every non-terminal durable job state;
- admitted, non-terminal EchoMind, Secretary, CRM, speech and imaging audit
  events, including the synchronous Lumbar Vision route;
- a stable service-owned process tree, with unknown child images rejected;
- every owned TCP socket whose state is not `LISTEN`, including child-process and
  `CLOSE_WAIT` sockets; and
- every open job/source file handle held by the service or its children. On
  Windows this uses the native system handle table and duplicates file handles
  for bounded path resolution, so raw `CreateFileW` handles held by
  `SourceLease` are covered even when `psutil.Process.open_files()` omits them.
  The one exact root-level `.server.lock` handle required by the verified
  `DirectoryLease` implementation is classified as the service lifetime lease,
  not active work. A missing or duplicate root lease fails closed, while a
  similarly named file below a job directory remains active job state.

Two identical process-tree samples are required before an observation can be
trusted. Access denial, malformed state, process disappearance, probe failure,
unknown children, source/release drift or schema drift produces only
`completion_uncertain`; there is no default-zero fallback. Handler lifecycle is
bounded by the service process's non-listening sockets, while child/provider/CRM
activity is covered by the full owned-process socket aggregate and admitted audit
events. A persistent child socket therefore reaches the outer fence timeout and
cannot be mistaken for idle.

A transient uncertain sample resets the complete idle proof and keeps the grant
fence active for another bounded observation. It never counts as zero. Only a
new fully trusted stable-idle interval may permit transition; persistent
uncertainty reaches the timeout, aborts before service control and restores the
exact grants. This prevents a racing handle close from causing repeated
disable/restore cycles while preserving fail-closed behavior.

The active legacy source also keeps one `requests.Session` connection to its
configured loopback PACS HTTP endpoint after bounded authentication or metadata
reads complete. The bootstrap contract permits only the reviewed loopback port
8000 endpoint with a maximum of one connection, plus the exact API
`service_host` child PID and process creation time. The selected process must be in
the verified service tree, use the selected source and have the reviewed
`-m modules.ai_imaging.eagle_eye_remote.service_host` command; a CRM or unknown
child can never qualify. Such a connection remains active for at least 75
seconds before it can be classified as a retained pool connection.
Qualification is tied to the owning process identity (PID plus creation time)
and complete local/remote TCP tuple; PID reuse or a changed tuple restarts the
timer. Opaque SHA-256 tuple-age state can cross an
isolated probe boundary without exposing process or endpoint details. Only
`ESTABLISHED` qualifies. Additional connections and `CLOSE_WAIT`, `FIN_WAIT` or
unknown states remain active. The age is not sufficient by itself: jobs,
admitted audits, source/job handles and inbound Eagle Eye connections are
independent zero-required blockers, so this narrow non-clinical pool
classification cannot hide accepted work. No socket is reset or closed by the
observer.

The manifest reader accepts either the deployment `release_id` contract or the
legacy immutable `candidate_revision` contract, but rejects conflicting
identities and always requires the caller-pinned manifest SHA-256. Native handle
enumeration is also fail-closed: access denial, a changing/unresolvable owned
file handle, an incomplete table or an oversized query blocks idle proof.

## Route coverage

The synthetic HTTP guard verifies an already-issued human session is rejected
after the fence for authentication introspection, usage, jobs, CRM, cases,
speech, Secretary, EchoMind and Lumbar Vision. Public read-only capabilities
remain available. This proves the current handler contract; the Razi operator
must still compare the active immutable revision before applying the fence.
The current handler also terminalizes the same durable audit event before
writing an HTTP reply and marks an admitted request `interrupted` when a
provider-side or peer-side connection failure escapes before a reply. Historical
`admitted` events are never cleared by the observer.

## Evidence

- Fail-before: the new guard failed because the bootstrap fence module did not
  exist.
- Pass-after: `20 passed` for the fence and `24 passed` for the aggregate observer.
- Combined observer, fence, future admission and authentication suite: `107 passed`.

The source and tests are guarded, but no live grants, service, listener, network
rules or revision pointer were changed by this work. Full candidate parity,
reviewed host observation, controlled SCM transition, authenticated Lumbar
request acceptance and rollback verification remain separate live gates.

## Live transition outcome

The separate live gates subsequently completed on 2026-10-10. Razi now runs
`20261010-reconciled-lumbar-language-r3`. The controlled transition required a
fresh trusted idle interval, changed the managed service revision, restored the
exact human grants and did not reset a TCP connection or stop PACS. The active
receipt verifies the SCM state, API working directory and all 8,569 active source
file hashes. Public capabilities advertise Lumbar protocol 1,
`derived-card-images-v1` and all 15 supported stages.

An authenticated request from the real Client used a synthetic nonexistent
study and no images. It reached the Lumbar handler and returned the exact
case-verification denial (HTTP 403), proving that the route, human session,
module grant and capability negotiation are active without invoking a provider
or sending patient data. A real selected-study/provider run and source-GUI
acceptance remain separate pending gates.

Receipts:

- `generated-files/eagle-eye/reconciled-lumbar-language-20261010-r3/active-receipt.json`
- `generated-files/eagle-eye/reconciled-lumbar-language-20261010-r3/controlled-transition-attempt2.json`
- `generated-files/eagle-eye/reconciled-lumbar-language-20261010-r3/authenticated-lumbar-acceptance.json`
- `generated-files/eagle-eye/reconciled-lumbar-language-20261010-r3/live-language-acceptance.json`
