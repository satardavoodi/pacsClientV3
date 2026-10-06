# Secretary brain / MCP alignment

The server brain and workstation control are one distributed system: Eagle Eye
owns planning/prompts/models; the client owns identity, permissions, GUI and
execution. A matching action name alone is insufficient.

## Verified gap and implemented correction

The prior protocol sent text/memory/modules to the server, which planned against
static server documents and validators. The actual workstation registry was not
part of the request. A server could propose an installed-catalog action whose
adapter or module launcher was absent on that client.

CommandBus now exposes capabilities() and get_control_capabilities. The snapshot
contains actual registered action names, entity JSON schemas, typed-schema
coverage, side-effect classification, assistant permission and confirmation
requirements. Convenience module aliases with no configured launcher are omitted;
generic open_module lists configured launcher names in its schema. This is
registration/configuration availability, not proof that live prerequisites hold.
No widgets, patients, credentials or files are inspected to construct it.

The canonical SHA-256 digest covers version and action contracts. The company
orchestrator sends the snapshot on planning; AgentBrain does so when its executor
has a bus. Execution repair and deferred GUI repair retain the planning snapshot.
The repair helper APIs also accept an optional snapshot.

Server-side strict models validate version, size (64 KiB), count (200 actions),
unique action names and digest. Server routing sees registered names; planning
sees the quoted runtime schemas alongside server-owned module documents. Server
output is restricted to the intersection of its validated actions and permitted
runtime actions. Runtime confirmation can strengthen, never weaken, the existing
server/client confirmation policy.

Responses acknowledge capability_digest. The client rejects absent/mismatched
acknowledgment, actions outside the permitted snapshot and invalid typed entity
arguments before returning an executable proposal. The local registry still
performs current permissions/identity checks at execution. A digest is a version
binding, not authentication or permission: authenticated Eagle Eye transport and
local device/user policies remain authoritative.

## What the brain must know

| Contract dimension | Authority | Practical rule |
| --- | --- | --- |
| Actual executable action | Client runtime snapshot plus server allowlist | Never infer availability from a catalog heading alone |
| Parameters/types | Snapshot schemas and local validation | Never invent paths, keys or unsupported fields; typed_entities=false means legacy incomplete schema coverage |
| Meaning/how to perform | Server-owned module documents | Education navigation does not save a case; Comment Sync differs from private Note |
| Live prerequisites | Local status/context actions | Recheck active study, microphone, module gate, local data and operation state |
| Authorization | Local CommandBus and Gateway policy | Server proposes; local confirmation remains binding |
| Immediate result | CommandResult | Accepted/opened/running is not a final save/send receipt |
| Final result | Owning status action / actual worker acknowledgment | Saved WAV and uploaded attachment are separate from reception delivery |
| Dependent steps | Actual preceding result handle | Never invent draft_id, recording_id or operation_id |

The server now stops a handle-dependent compound proposal at the safe prefix
that produces the handle. Current workflow execution cannot generally bind all
future results into server-generated steps. Continuation must inspect the actual
result and make a subsequent request; automated server observation/continuation
is still outstanding. This guard prevents a planner from pretending the later
operation already has a valid handle.

## Examples and limits

- Patient Comment Sync: get the actual study context, prepare the comment,
  inspect its draft_id, obtain local confirmation, sync that draft and poll
  patient_comment_status. Neither report status nor private Note is substituted.
- Voice: prepare the study-bound take, inspect preparation, start, pause/resume,
  stop and wait for the actual WAV receipt. Confirm upload of only that take;
  reception_delivery_confirmed remains false without a reception receipt.
- Support: collect bounded evidence, inspect operation_id and poll. Resource/
  severity/exception counts are observations; they are not an established cause
  or ticket submission.
- Settings: use existing theme names and operation polling. Personal credentials
  and prompt entry remain in the local form; cleanup uses existing confirmation.
- Education/Advanced/image understanding: respect the earlier documented gaps.
  A registered navigation/capture command does not establish case persistence,
  a working analysis/export bridge or remote multimodal understanding.

## Compatibility, deployment and completion criteria

Runtime snapshot is an optional protocol-1 extension on the server for legacy
callers. Calls without it remain catalog-only and are not verified runtime
alignment. New canonical client calls carrying it fail closed against older
servers rather than fall back to company-direct inference. Deploy a matching
server/client pair before claiming the new handshake works in production.

Full alignment requires typed schemas for legacy actions, outcome contracts for
every adapter, verified live prerequisites, actual result-driven continuation,
deployed catalog/validator parity and live source tests for each workflow.
Current source improvements do not justify a 100-percent end-to-end claim.

## Verification receipt

Initial alignment guards: three fail-before failures. Final direct focused suite:
189 passed, one host-restricted symlink skip, three existing TLS deprecation
warnings, exit 0. Synthetic coverage verifies snapshot content, strict/digest
validation, absent action rejection, typed argument rejection, server filtering,
response acknowledgment, confirmation metadata, missing launcher omission and
handle-dependent workflow boundaries; adjacent Secretary/Gateway/control tests
also pass.

Eleven owned EchoMind Python mirrors match after scoped synchronization; server
snapshot hashes and support catalog are updated in source. Global mirror parity
retains the unrelated shared chat-page drift recorded in the preceding receipt.
Syntax/document checks pass. No server deployment, release build, clinical
execution or live GUI acceptance occurred; Test Control remains unavailable.
This is an OPT-23 follow-up, with unrelated worktree changes preserved.
