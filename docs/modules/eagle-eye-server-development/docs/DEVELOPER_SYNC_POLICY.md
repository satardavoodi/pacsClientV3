# Mandatory local/Razi Developer synchronization

Owner decision: 2026-10-08. This is a required completion and build-handoff gate,
not an optional reminder. It applies to all developers and agents working on the
workstation and Eagle Eye Server development line, regardless of which host
originates a change. Existing clinical, ownership, security and release gates
continue to apply.

## Scope and authority

The local workstation repository and the selected Razi Developer source revision
must contain the same reconciled source, tests, documentation, role definitions,
UI resources and packaged mirrors. Required model/native assets must use the same
approved source/weight revisions with recorded hashes. Client and Server behavior
may intentionally differ by role; that is not permission to fork their source.

The local root is currently
`E:/ai-pacs/ai-pacs codes/ai-pacs beta version`. Razi development is under
`D:/Eagle Eye Server`. Resolve the selected revision from current deployment/parity
receipts, not from a hardcoded historical folder or a running service assumption.
At adoption, the reconciled candidate is `revisions/20261008-reconciled-developer/source`;
the active service still selects r4. This rule does not activate the candidate.

## Required workflow for every change

1. Inspect both Developer sources and their outstanding differences before edits.
   Preserve unrelated work and record the base hashes of affected files.
2. If both sides changed, reconcile behavior and history. Select the newest correct
   implementation with tests and subsystem contracts. Do not select by file date,
   copy one tree blindly, or discard server-only corrections.
3. Implement and verify the change; update existing regression guards and relevant
   documentation. Synchronize packaged mirrors using the existing tools.
4. Apply the resulting change to the other Developer side in the same work session.
   Include source, tests, documentation and required assets. For an executing
   revision, prepare a new versioned candidate rather than modifying live code.
5. Compare the complete declared source/resource inventory by SHA-256. Verify
   required model/native revision identity separately from host runtime layouts.
   Classify every missing, additional or differing file; no unexplained delta is
   permitted. Retain a receipt on both hosts with roots, manifest digest, counts,
   decisions, tests, exclusions and activation state.
6. Before reporting completion or handing off a build, recheck for concurrent
   changes since the snapshot. Any new delta reopens reconciliation. A build must
   additionally satisfy BUILD.md and RELEASE.md; source parity alone is insufficient.

## Exclusions and blocked work

Credentials, license/device identity, certificates, patient data, databases,
private logs, job queues, hardware paths and host-specific configuration are not
source and must not be copied between hosts. Environment and runtime layouts may
differ where explicitly recorded and verified for their host. Exclusions cannot
be used to hide missing source or incompatible model/native assets.

If the other host is unreachable, its work is in progress, or reconciliation/tests
fail, retain the reviewed pending delta and evidence, report synchronization as
blocked, and do not declare the change complete or hand it off for a build.
Never resolve a conflict by deleting private state or overwriting another owner's
unfinished changes. Routine synchronization is already authorized by the owner;
separate permissions and acceptance still govern clinical/service activation.

## Source parity versus running-service parity

Report these separately: synchronized Developer snapshots, validated payloads,
automated tests, live source-GUI acceptance, and activated service revision.
Updating files or staging a candidate does not update an existing process.
Activation requires the existing service ownership, queue, licensing, rollback and
acceptance workflow. Do not silently restart clinical work to obtain parity.

This document and both hosts' AGENTS.md entry points provide durable project
memory. They are a mandatory workflow contract; they are not an unattended file
watcher or evidence that future edits have already synchronized.

## Test and build ownership (2026-10-09)

Razi runs the current reconciled Server Developer snapshot for Function Tester and
server function scenarios. The local control computer runs the source Client for
Client/Server integration and builds both products after acceptance. Running-source
identity must match the tested snapshot. See [the owner workflow](DEVELOPER_TEST_BUILD_WORKFLOW.md).
