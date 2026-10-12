# Eagle Eye Server development workspace

## Connection boundary authority - owner clarification, 2026-10-12

[Canonical Eagle Eye connection boundaries](../../architecture/EAGLE_EYE_CONNECTION_BOUNDARIES_2026-10-12.md) supersedes historical pairing and TLS requirements below.

Eagle Eye Server ingress uses HTTP IP:port plus username/password: Windows EchoMind, Secretary, CRM and imaging; mobile EchoMind, Secretary Agent and CRM. The server resolves PACS first, tries Reception only after credential rejection (401), then enforces internal feature/module grants. Caller-supplied PACS/provider tokens and device pairing are not required. An opaque session issued by Eagle Eye after password login is an internal implementation detail, not a caller-provided PACS token.

QR/device pairing and HTTPS belong only to mobile Android/iOS remote Agent PACS connections to Windows DICOM Client, including endpoints without static IP. Windows uses native Secretary rather than a remote Agent PACS client. Mobile currently has no imaging AI feature.

Implementation audit: the active snapshot retains optional legacy provider/upstream-token admission and optional legacy TLS compatibility on a listener that also accepts HTTP. This documentation does not claim the legacy token route has been removed. No runtime edits, service restart or build is authorized by this documentation synchronization. Historical receipts remain preserved below; current contract and deployed acceptance are distinct.


**Human authorization (2026-10-09):** [Two independent access gates](docs/USER_AUTH_PROTOCOL.md)
require a verified PACS or Reception identity and separately approved Eagle Eye
feature/module grants. Device pairing alone cannot admit work. Server-only User
settings manage approvals and per-user audit history. Source tests and deployment
acceptance are separate; pending gates are recorded in CURRENT_STATE and BACKLOG.

**Server console identity (2026-10-09):** [Server-only authentication and
same-host deployment contract](docs/SERVER_CONSOLE_AUTH.md). Offline and Demo
console admission are disabled for Server only. Local guarded implementation;
live GUI, Razi activation and complete parity remain separate pending gates.

**Current September 30 checkpoint:**
[Hosted EchoMind and versioned Developer service](docs/ECHOMIND_SERVER_2026-09-30.md).
The active listener is paired TLS 8002, not the historical pilots described below.
Actual EchoMind API and hidden native startup gates pass; full GUI/model acceptance
and installer production remain separate.

Updated: 2026-09-23. Deployment root: `D:\Eagle Eye Server` on Razi Reception.

This workspace develops the server edition of AI-PACS Eagle Eye. Standard clients
control analyses and review results; server workers obtain source images from PACS
and execute AI models. Heavy weights and inference environments belong on the server.

**Current milestone: full workstation source/UI transferred; human sign-in succeeded,
but GUI acceptance FAILED with a native Advanced fault.** DICOMs reached the local
cache, but rendered output and complete study acceptance are not certified. The
independent service responds on 8043; the original 8042 pilot remains preserved.
Model deployment/import checks do not establish clinical inference qualification.

## Start here

**Latest:** [Full workstation source and UI deployment](docs/FULL_WORKSTATION.md).

[Automatic Windows service and PACS account settings](docs/SERVICE_AUTH.md).
The independent service runs on 8043; the original 8042 pilot remains unchanged.

1. [Current state and installed components](docs/CURRENT_STATE.md)
2. [Architecture and client/server responsibilities](docs/ARCHITECTURE.md)
3. [Development workflow and code map](docs/DEVELOPMENT.md)
4. [Operation, logs, diagnosis and recovery](docs/OPERATIONS.md)
5. [Test plan and acceptance evidence](docs/TESTING.md)
6. [Ordered remaining work](docs/BACKLOG.md)
7. [Decisions and change history](docs/HISTORY.md)
8. [Developer and agent agreement](AGENTS.md)

Open this directory in VS Code. The full UI source is
`revisions/20260923-workstation/source`, with its own `.venv`. The existing
8042 pilot still uses `revisions/20260923-dev/source` and `runtime/Scripts/python.exe`. Read the development workflow before changing an
executing revision. The source snapshot is a reviewed subset, not a complete Git
checkout or a complete portable model bundle.

`deployment.json` and `Run-EagleEye.ps1` describe the selected revision/runtime.
`docs/DOCS_MANIFEST.json` identifies this documentation snapshot. Update these docs
after each meaningful change; do not leave stale success claims or unresolved
failures hidden in chat history. Do not put credentials or patient data in docs.

No restart, endpoint change or model run is required to read these documents.

Secretary course/media and public web asset implementation: [content workflow and activation gates](../../agent_control/SECRETARY_CONTENT_WEB_ASSETS_2026-10-09.md). Default static web reads have no browser dependency; optional dynamic browser and image generation require staged configuration and live acceptance.

## Current-request language source receipt (2026-10-10)

See [the shared language contract](docs/REQUEST_LANGUAGE_2026-10-10.md) for Secretary/CRM preference negotiation, tests and explicit pending Developer parity/activation/live gates.

## Legacy first-transition admission fence (2026-10-10)

See [the reversible bootstrap fence](docs/LEGACY_BOOTSTRAP_ADMISSION_FENCE_2026-10-10.md)
for the old-revision grant fence, last-verification race handling, exact rollback
and the host-observer evidence required before the first controlled service
transition. It is guarded source, not a claim that Razi was activated.

## Private cooperative transition source (2026-10-10)

[Admission and safe transition contract](docs/SAFE_TRANSITION_2026-10-10.md) records inactive source counters, private owning-parent control, synthetic tests and the explicit old-active bootstrap blocker. No activation or full Developer parity is claimed.

## Prepared password-only admission source - 2026-10-12

[Implementation and compatibility gates](docs/PASSWORD_ONLY_ORDINARY_AUTH_2026-10-12.md). Caller provider/upstream_token exchange is removed from the prepared source; ordered username/password authentication and internal sessions remain. Active Razi candidate02 is unchanged until reviewed immutable deployment. Client/Android/iOS migration and live acceptance are separate gates.
