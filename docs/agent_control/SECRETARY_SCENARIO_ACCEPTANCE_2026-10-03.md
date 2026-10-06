# Secretary scenario acceptance — 2026-10-03

Scope: current shared MCP/CommandBus, Secretary execution and authenticated Eagle Eye planning contracts. No clinical data deletion, live download, physical CD burn or credential mutation was performed.

## Automated results

Two direct pytest runs exited 0: 129 tests in the Home/settings/capability/workflow selection and 49 tests in the server/patient interaction/result presentation selection. These are 178 successful test executions, not 178 unique tests; settings tests overlap. Existing SWIG deprecation warnings remain.

| Requested scenario | Automated evidence | Remaining live acceptance |
| --- | --- | --- |
| Modality/body-part/date search, sorting and exact first/third selection | Home advanced, sort and selection guards | Real filters, visible row order and identities |
| Search then open first result | Ordinal contract/executor and receipt chaining guards | Fresh server plan acknowledging updated runtime schema, opening exact study |
| Download multiple selected studies | Exact selection/receipt and stale selection guards | Real queue terminal completion |
| Prepare CD/Filming | Media preparation, local availability, confirmation and output safeguards | Native dialogs; hardware/blank media for physical burn |
| Settings navigation | Lazy child navigation guards | Visible Settings pages |
| Available RAM and disk space | Asynchronous resource diagnosis guard | Current resource receipt |
| Cache/printing cleanup | Deferred local confirmation, duplicate request and worker-result guards | Confirmation/cancel flow; any deletion requires concrete local review |
| AI settings | Secure local form handoff and secret rejection guards | Visible form; no provider/key changes |
| Viewer/image-filter settings | Section navigation and schema guards | Actual supported setting controls; navigation alone is not configuration acceptance |
| Patient comments/voice | Shared control contracts, preparation and status guards | Native recording and actual reception delivery |
| Server/brain compatibility | Server contract, capability digest, receipt bindings, unified MCP entrypoint guards | Actual Persian command through live server and native client |

## Extended controls implemented after the initial review

Local patient deletion is now exposed with explicit all/delete_oldest_count/older_than_days strategies, local preview/default-No confirmation and real worker status. The oldest 30 local dated patients differs from the last 30 visible rows; clarify that distinction. release_memory trims only the current Windows process working set and reports measured resident bytes. Viewer backend/GPU preferences are persisted off-thread and read back, with restart_required. Personal AI secrets remain local-only and company AI settings remain server-owned. See SECRETARY_EXTENDED_SETTINGS_2026-10-03.md for the code/test receipt.

Final server revision 20261003-secretary-settings-final is active. Target contract guards passed 28 tests and pip check. Authenticated real planning produced release_memory then settings_operation_status with capability digest acknowledgment; no client command or deletion was executed by that planning test. Native client acceptance remains pending.

## Live connection gate

The documented aipacs-control client ping could not connect to AIPACS_TEST_Dr_Alizadeh (QLocalSocket Invalid name). No live GUI pass is claimed. A human fresh source launch using run_app.ps1 -TestServer and sign-in is required before ping/list_actions and affected native workflow acceptance. Do not launch a second app or terminate clinical work to enable it.


## Pipeline execution boundary audit (late session)
The latest real voice attempt transcribed successfully and routed to Settings but exhausted repairs on open_settings. Root cause: _run_plan_steps unconditionally added source after validation, so strict unrelated bus schemas rejected the command; source_scope could also inject source during preplanning. Both binders now consult declared typed or legacy entity contracts. Strict schema checks remain unchanged; unsupported caller fields are not silently dropped.

Fail-before: 48 typed action guards failed at the execution boundary. Pass-after: 74 boundary/integration tests, including all 10 Settings sections through server proposal normalization, client proposal validation, scoped request binding, real SecretaryExecutor/CommandBus/SettingsCommandAdapter and actual offscreen Qt tab navigation. The provider is deterministic in these integrated tests; they do not claim real LLM navigation acceptance.

Broader source suite: 401 passed, one skipped because host does not permit symlinks. Covered Secretary routing/planning, runtime schemas, Home filters/selection/download, settings navigation/resources/cleanup/viewer controls, confirmations/clarifications, memory, modes, speech UI, support/ticket packaging and workflow receipt polling. Ten additional integrated Qt tests then passed (aggregate 411 unique passing source tests). The initial broad run exposed an outdated raw-log consent expectation after the already-implemented package-v3 migration; corrected the guard to verify v3, CRC-valid logs.zip inclusion and identical frozen package on retry, using a temporary archive root. Builder support payload parity initially exposed a stale Secretary source snapshot receipt for previously implemented support/validation updates. Refreshed only owned mode/clarification/support source hashes, retaining separate active deployment receipts; both builder guards then passed. Scoped orchestrator mirror synced and hash-verified.

Native acceptance: documented control client ping still cannot reach AIPACS_TEST_Dr_Alizadeh. No installed app, new source instance, login, clinical data mutation or server restart was used for this client fix. The existing human source session must be restarted to load it; real repeated-voice and affected native workflow acceptance remain pending. Active Razi server already passed paired synthetic mode/Settings/clarification checks in the previous activation; this fix is client-only.

Scope limits: opening configuration is not changing a modality catalog. Persistent modality mutation remains an explicit local configuration handoff until a real typed mutation capability is implemented. Synthetic adapter success or accepted planning is not a completed live clinical workflow.


## Owner-provided Settings examples - individual acceptance
Eight synthetic requests were sent to the active paired Razi Eagle Eye listener with the current Settings-capable runtime snapshot. Capability digest was acknowledged for every proposal. No workstation actions were executed by this server probe. Projected results are in generated-files/echomind/settings-scenario-results-20261003.json.

| Example | Actual active server proposal | Functional acceptance |
|---|---|---|
| Verify configured Razi DICOM ports 105 and 104 | unknown, no modules | Secretary verification action is unsupported. Independent real DICOM C-ECHO using configured endpoint/AET succeeded on 105 (Status 0); association failed on 104. No configuration writes. |
| Copy existing Mehr server as Mehr 2, then Verify | open_settings server | Navigation only; no clone or Verify capability. No real server record added. |
| Remove NM and XA from Modality Grid | open_settings viewer | Navigation only; no modality mutation capability. |
| Delete all local Patient Data contents | request_storage_cleanup patients/all, confirmation requested | Existing bounded cleanup flow available. Synthetic local test verifies awaiting_local_confirmation, no deletion-complete claim, and terminal counters. No actual patient deletion or root folder removal tested. |
| Reference Line color red | open_settings tools | Navigation only; no tool-style mutation capability. |
| Arrow Tool width 5 | open_settings tools | Navigation only; no tool-style mutation capability. |
| CT min_slices 4 to 5 | configure_image_quality image_filter | Local editing handoff; changed=false. No parameter write. |
| MR min_slices 4 to 5 | configure_image_quality image_filter | Local editing handoff; changed=false. No parameter write. |

125 focused tests passed, including seven owner-example execution/receipt tests with synthetic local Qt shells and cleanup panel, previous Settings/source-binding integrated guards, strict schemas and result presentation. The first run exposed four misleading open_settings replies saying the requested action completed. Minimal presenter fix now explicitly reports that only Settings opened and no configuration changed; four guards failed before and passed after. Initial test assumption of a separate bus cleanup confirmation was corrected to test the real Secretary executor and existing local Storage confirmation, rather than claiming two implemented gates.

Native source GUI acceptance is still separate and unavailable through the documented control socket. These observations prove planning behavior and bounded synthetic local execution, not complete automatic support for the missing mutations. New typed server verification, clone, modality, tool-style and filter controls would require a separate implementation slice; no fabricated capability is advertised here.

## Subsequent typed-controls implementation

The missing controls above are now implemented and deployed to the Razi Eagle Eye developer service. See [the implementation and verification receipt](SECRETARY_TYPED_SETTINGS_CONTROLS_2026-10-03.md). The earlier table records the pre-implementation audit, not the current capability set. Configured-server Verify, independent cloning, Modality Grid removal, tool color/width and scalar CT/MR filter changes have shared typed actions, worker execution, confirmation and terminal readback. Existing patient cleanup remains locally confirmed. Native GUI acceptance remains pending; array-valued filters retain an explicit local UI handoff.
