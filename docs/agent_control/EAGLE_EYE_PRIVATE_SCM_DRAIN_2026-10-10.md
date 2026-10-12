# Private administrator cooperative service drain

`service_control.py` adds a private, correlated user-defined SCM control 128.
It has no HTTP endpoint, credentials, process kill or SCM STOP fallback. This is
preparation source only; no clinical activation or Windows ACL qualification has
been performed.

An administrator explicitly runs `provision(config_path, expected_identity)` before source use. The fixed
request directory allows only System/Administrators to write and LocalService to
read. The separate response directory allows LocalService to write. The validator
checks owner, allow ACEs, reparse boundaries and ancestor replacement rights.
An INHERIT_ONLY ACE is ignored for the inspected object because it does not grant
effective rights there. Effective untrusted writes, delete-child rights and
unprivileged owners remain rejected. This matches standard ProgramData/drive
ancestor ACLs without modifying them. Actual A100 primitive verification exposed
the former false rejection; seven synthetic flag guards cover this correction.
The exact OS TrustedInstaller service SID may own or write only higher ancestors
(depth greater than one), after resolving NT SERVICE\TrustedInstaller and checking
its canonical SID. It cannot own the private target, its immediate parent or a
response root. Other service SIDs and effective common write/delete-child rights
remain rejected. Higher-ancestor create-file/directory rights alone cannot replace
an existing protected child and do not trigger the replacement-rights check.
These are Windows operating-system rights; PACS administrator status does not
grant control-channel access or process-query privileges. AccessDenied fails closed.

`stop_when_idle(config_path, expected_identity, deadline_monotonic)` requires a
reviewed source manifest, source/runtime/base/entry/config paths and SHA-256s,
exact SCM command, current service PID and creation time. It revalidates reviewed
bytes, live SCM LocalService ownership and process identity before publication and
again before SCM dispatch. The host independently recomputes its identity. A
request has strict canonical UUID correlation, protocol, operation, UTC issuance
and deadline, with at most 120 seconds of requested budget. JSON is bounded to
16 KiB, rejects duplicate members and nonfinite values. Replays and concurrent
controls are refused; a restarted supervisor cannot adopt an old PID identity.

The host API is `ServiceControlHost(config_path, identity_getter, safe_transition,
diagnostics)`, `handle_control(128)`, `busy`, and `wait(timeout)`. The lifecycle owner
must wait for its worker before returning from the SCM service framework. Host
code never sets the emergency stop event. The supervisor callback returns true
only after its private native-aware drain commits closed, zero work and no
uncertainty, and the owned child has exited successfully. A false result or an
exception never requests a forced service stop. A lost response is unknown even
if cooperative close completed; the caller must inspect and never force retry.

Source provisioning writes protected `service-control-target.json` with explicit
reviewed manifest path/digest and static identity. PID and creation time are never
persisted as reusable authority. `live_identity` pins source config bytes; legitimate
config changes require separately reviewed target publication. Frozen service
identity derives the canonical own core release manifest and executable and reads
the current protected config, allowing the fresh installer to remove its internal
barrier selector. This does not authorize rewriting a source target automatically.
Full source inventory parity remains mandatory before activation; each private
control rechecks manifest, entry, runtime/base and config hashes rather than hashing
all source inventory again.
Complete target-file SDDL literals are checked by the actual Windows security
descriptor parser. File ACEs use an empty flags field followed by FA/FR rights;
directory OICI inheritance remains explicit. This parser check does not modify
any ACL and does not replace owning-host file roundtrip qualification.

The framework reserves `stop_timeout + 4` seconds (24 by default) for acknowledgment,
child close and receipt persistence. Supervisor lock acquisition uses the remaining
drain deadline. A before-close hook waits for the control worker before pipes and
Job resources are closed. An abnormal callback exceeding its expected bounded
lifetime keeps the service and owned resources alive for inspection; it never
converts missing completion into emergency stop. Such a retained service requires
operator review. Ordinary emergency SCM STOP behavior remains a separate existing
path and is never invoked by this private control.
No client token or patient payload is written to control records. Records contain
private host paths and process identities and stay on their owning host.

Focused synthetic verification: 20 transport tests and 47 combined service/control
tests passed with exit code zero. This covers
changed reviewed bytes, exact positive completion, refusal, unknown completion,
expired/malformed/replayed requests, concurrent controls, missing acknowledgment
protected-access denial, concurrent request replacement correlation, supervisor
lock contention and receipt-before-resource-close ordering. Actual SCM/ACL/process-query and native GUI drain
acceptance remain separate Windows A100 qualification gates.
