# Eagle Eye Server local development agreement

## Connection boundary authority - owner clarification, 2026-10-12

[Canonical Eagle Eye connection boundaries](../../architecture/EAGLE_EYE_CONNECTION_BOUNDARIES_2026-10-12.md) supersedes historical pairing and TLS requirements below.

Eagle Eye Server ingress uses HTTP IP:port plus username/password: Windows EchoMind, Secretary, CRM and imaging; mobile EchoMind, Secretary Agent and CRM. The server resolves PACS first, tries Reception only after credential rejection (401), then enforces internal feature/module grants. Caller-supplied PACS/provider tokens and device pairing are not required. An opaque session issued by Eagle Eye after password login is an internal implementation detail, not a caller-provided PACS token.

QR/device pairing and HTTPS belong only to mobile Android/iOS remote Agent PACS connections to Windows DICOM Client, including endpoints without static IP. Windows uses native Secretary rather than a remote Agent PACS client. Mobile currently has no imaging AI feature.

Implementation audit: the active snapshot retains optional legacy provider/upstream-token admission and optional legacy TLS compatibility on a listener that also accepts HTTP. This documentation does not claim the legacy token route has been removed. No runtime edits, service restart or build is authorized by this documentation synchronization. Historical receipts remain preserved below; current contract and deployed acceptance are distinct.


Read README.md and docs/CURRENT_STATE.md before changing anything. All project,
system, source, comments, logs and documentation additions are written in English.

The user authorized source development under `D:\Eagle Eye Server`. This does not
make unfinished models clinically qualified. Preserve the live PACS, CRM and legacy
Breast processes. Existing coordination rules and the user's current instructions
take precedence over this local guide.

## Mandatory two-way Developer synchronization — owner decision, 2026-10-08

Every change on this Razi Developer project or the local workstation Developer
project must be reconciled and applied to the other side in the same work session.
Inspect both sides, preserve independent work and choose the newest correct code
by history, behavior and tests, never timestamps alone. Completion and build
handoff require recorded file-hash and required-payload parity. If access or
verification is blocked, record the pending delta and block completion/build
handoff. Host-private state is excluded; executing code must not be overwritten.
Source synchronization and service activation are separate acceptance states.
Read [the mandatory contract](docs/DEVELOPER_SYNC_POLICY.md).

- Inspect current state and source differences before editing. Do not overwrite
  another developer's uncommitted work or an executing source revision.
- Keep credentials, patient identifiers, DICOM, reports and private logs out of Git,
  documentation, screenshots and external AI services. Use synthetic regression data.
- Use the dedicated environment; never install packages into shared system Python.
- Do not replace System32 DLLs or globally upgrade runtimes to fix this pilot.
- Do not kill processes by name. The scheduled task alone did not stop its listener;
  follow the ownership and empty-queue verification in docs/OPERATIONS.md.
- A capabilities response is transport evidence, not model readiness. Empty PACS
  allowed_roots is deliberate until authoritative source mapping is validated.
- Slicer/build changes belong to the build workstream. Shared PACS acquisition,
  identity and cache coordination belong to Unify. Eagle Eye consumes those contracts.
  Preserve separate Fast, Advanced and VTK viewer execution domains.
- Runtime fixes require a fail-before regression guard and relevant acceptance.
  Run guards on the canonical repository when not present in this subset. Never let
  tests open the live clinical database. Record automated and live gates separately.
- Use a new versioned candidate for source, environment or asset updates. Record
  hashes, test receipts, limitations and rollback before activation.
- Update CURRENT_STATE, BACKLOG and HISTORY after a change. Do not silently edit
  deployment.json to claim a result that was not observed.

Two isolated development hosts exist: the original manual task on 8042 and the
automatic SCM service on 8043. Read docs/SERVICE_AUTH.md before lifecycle work.
Reboot, real account, full model, resource and installer qualification remain required.
