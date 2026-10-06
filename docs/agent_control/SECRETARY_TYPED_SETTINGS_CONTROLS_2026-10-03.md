# Typed Secretary settings controls

The scenario audit found that navigation was being offered instead of configuration changes. Six shared CommandBus controls now implement asynchronous snapshots, configured-server DICOM verification, independent server cloning, modality removal, tool styling and scalar CT/MR filter updates.

Eagle Eye owns planning and the catalog; the workstation owns persistence, permissions and execution. Every control returns a real operation ID and uses settings_operation_status verification. Mutations require confirmation and fail closed in read-only mode. Credentials and arbitrary paths cannot be command entities. Verification never changes an active connection and only DICOM status zero counts as C-ECHO success.

The worker repository reads and writes local configuration. Paired server/profile and filter/preset writes have rollback and readback checks. Concurrent edits observed after a read are rejected. Cloned profiles retain socket/module endpoints but receive independent identity. Removing all modalities is rejected; Home options refresh using an in-memory receipt. Tool changes use the existing isolated-testable SQLite storage and only publish cache updates after persistence. Array-valued filter parameters remain a local UI handoff; scalar enable flags and bounded numeric parameters are supported.

Configuration changes report restart_required. Existing Settings forms and active images are not silently reloaded or reprocessed. Restart the single source client after saving to refresh all forms; never restart active clinical work automatically.

## Verification

- Fail-before guard: repository tests initially failed collection because the missing implementation did not exist.
- Focused shared contracts, permissions, workflow polling, persistence and server guards: 155 passed before additional rollback/invalid-input guards.
- Staged Razi developer server: 37 guards passed; pip check passed.
- Live native client acceptance remains pending: the documented local control endpoint is unavailable. No live patient deletion or configuration mutation was performed for tests.
- Activated developer server passed paired authenticated Act/Ask/Guide/Help Ticket checks and seven typed-settings planning scenarios. Six requested the correct mutation/verify action; cloning first requested a settings snapshot. No live configuration commands were executed by these probes. Activation checked zero active model jobs and zero active Secretary/EchoMind requests; private configuration was preserved.
- Final focused run: 184 passed, including real MCP stdio inventory, worker receipts, invalid inputs, concurrent edits, paired-write rollback and exact DICOM success status.
- A separate authenticated synthetic continuation supplied the completed server snapshot: Eagle Eye returned clone_settings_server followed by verify_settings_server with confirmation required. This checks planning continuity without cloning any live server.

## Developer server deployment gate

Scope: AIPacsEagleEye on the already authorized Razi developer service only. No workstation release, PACS server replacement or website deployment.

- CONFIRMED: source tests and isolated target tests passed before activation.
- CONFIRMED: scoped archive manifest and per-file hashes; prior revision remains available.
- CONFIRMED: API ownership and typed boundaries above; no new patient-data or credential exposure.
- CONFIRMED: activation script requires the expected host/service identity, unchanged private configuration, idle running-operation count, and authenticated contract checks; automatically restores the prior SCM command on acceptance failure.
- CONFIRMED: human authorization is the current request to implement server support, following explicit identification of Razi Eagle Eye developer as the target.
- N/A: clinical viewer/overlay acceptance for this server-only developer update; no rendering or workstation release is promoted. Client GUI acceptance is separately pending and is not claimed as passed.

Candidate: `D:/Eagle Eye Server/revisions/20261003-secretary-settings-controls/source`.
Previous: `D:/Eagle Eye Server/revisions/20261003-secretary-clarification/source`.
Receipts and exact rollback command: `D:/Eagle Eye Server/incoming/secretary-settings-controls-20261003/`.
