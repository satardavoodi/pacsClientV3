# Client LLM server authority - 2026-10-09

Owner decision: Windows DICOM Workstation, Android and iOS send LLM workflow
inputs to authenticated Eagle Eye Server. Provider selection, credentials,
models, prompts and upstream execution belong to Server AI Connection.
Remove affected client provider configuration and direct execution, including
personal API execution; the server Custom API profile supplies that capability.
Preserve the explicitly named Subscribe exception without guessing its meaning.
Speech transcription retains its separate existing policy pending clarification.
Client-owned UI, input collection, identity, local permission checks and confirmed
local command execution remain client-owned. Never execute arbitrary generated code.

Clients must not select LLM G/A/V/Custom per request or send provider secrets.
Existing server authentication and per-user permission admission remain mandatory.
Report unavailable/denied workflows explicitly; do not fall back directly upstream.
LLM A/V are currently reserved, not qualified inference routes.
Unsupported server workflows require explicit endpoint/payload migration before
removing their working client functionality. Preserve workflow capabilities.

## Ownership and current evidence

- Windows EchoMind: thread 01a099c1-7ccd-78b2-a100-36260fc77517 audits dispatch/settings.
- Android coordination: thread 01a11c5b-978b-73b1-902a-b58eb14572a5.
- iOS authoritative Mac: thread 01a12171-10f2-7971-9354-b2fa0812cdcf.
- Eagle owner owns server workflow gaps and immutable Razi reconciliation.
- All three implementation handoffs were delivered; completion receipts pending.
- Razi brain-profiles-r2: 23 scoped files rehashed equal to local; prior 101 guards.
- Active service still selects education-presenter; no service transition performed.
- Complete Developer parity, GUI/provider acceptance and safe transition remain pending.

## Lumbar derived-card migration status - 2026-10-10

The Windows lumbar MRI pipeline exposed a migration gap after direct company
senders were retired: Gate 1 still called the blocked desktop
`EagleEyeImageAnalysis` function. The captured evidence was valid, but no image
request reached Eagle Eye Server.

The source correction introduces a dedicated authenticated
`POST /v1/imaging/lumbar-vision` contract. It is not a general image upload or
text-chat fallback. The Client may send only an exact study binding, a canonical
stage ID/version, bounded derived evidence images, captions/card metadata and the
stage data header. The Server rejects client system prompts, model names,
provider selection, token budgets and sampling controls; reconstructs the exact
canonical stage; and owns company credentials and upstream execution. Derived
pixels are held only for the request and are not written to EchoMind history.

This source implementation does not activate the currently running Razi
revision. Immutable Razi staging, complete parity receipts, safe queue drain,
Function Tester/provider completion and local source-GUI acceptance remain
mandatory before the workflow is described as operational.

Track Android/iOS/Windows implementation, revision, automated checks, build,
GUI and real-server acceptance separately. This record is not acceptance or a
build/release authorization. Do not overwrite executing or selected immutable source.

### Lumbar Client/Server compatibility negotiation

The derived-card route now has a feature-level compatibility contract. The
Server advertises `lumbar_vision` only when the actual handler is available.
That object reports the enforced protocol, transport, supported stage ID and
stage-version pairs, and bounded request limits. The Windows Client reads this
public capability before it reads, encodes, or uploads any derived clinical
image. A missing capability identifies an older Server; a protocol or stage
version mismatch identifies incompatible pipeline revisions; malformed limits
fail closed. The Server retains its POST validation as defense in depth.

Whole-product version equality is deliberately not the runtime rule. Compatible
Client and Server releases may advance independently, while any incompatible
feature revision is blocked before paid/provider work. Full Developer source,
model-binding and packaged-mirror parity remain deployment requirements and are
not replaced by this negotiation. The currently active Razi revision does not
advertise this capability and remains incompatible; no activation is claimed.

Fail-before evidence showed two independent defects: the Server exposed no
dedicated lumbar capability, and an incompatible Client attempted to read image
bytes before any negotiation. Pass-after evidence is recorded in
`generated-files/eagle-eye/lumbar-vision-parity-20261010/compatibility-receipt.json` with
scoped source, test and documentation hashes. Focused compatibility/admission
guards passed 22 tests; remote transport passed 28; lumbar analysis passed 108;
routing/profile selection passed 32; explicit provider isolation passed 21.
Python compilation and scoped diff checks exited zero. The adjacent EchoMind
listener suite retains a pre-existing failure because its synthetic fixture
still asserts the old paired-device owner after human-principal hashing; this
change does not modify that ownership boundary.

Android and iOS treat unknown top-level capability fields additively and do not
call this Windows lumbar derived-card route. Android therefore records this
contract as not applicable with no source change. A fresh iOS assessment passed
17 related decoder tests and its build, also with no source change; no mobile
live-server acceptance was performed. These assessments do not qualify lumbar
inference on either mobile platform.
