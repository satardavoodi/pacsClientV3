# Current state and inventory

## Connection boundary authority - owner clarification, 2026-10-12

[Canonical Eagle Eye connection boundaries](../../../architecture/EAGLE_EYE_CONNECTION_BOUNDARIES_2026-10-12.md) supersedes historical pairing and TLS requirements below.

Eagle Eye Server ingress uses HTTP IP:port plus username/password: Windows EchoMind, Secretary, CRM and imaging; mobile EchoMind, Secretary Agent and CRM. The server resolves PACS first, tries Reception only after credential rejection (401), then enforces internal feature/module grants. Caller-supplied PACS/provider tokens and device pairing are not required. An opaque session issued by Eagle Eye after password login is an internal implementation detail, not a caller-provided PACS token.

QR/device pairing and HTTPS belong only to mobile Android/iOS remote Agent PACS connections to Windows DICOM Client, including endpoints without static IP. Windows uses native Secretary rather than a remote Agent PACS client. Mobile currently has no imaging AI feature.

Implementation audit: the active snapshot retains optional legacy provider/upstream-token admission and optional legacy TLS compatibility on a listener that also accepts HTTP. This documentation does not claim the legacy token route has been removed. No runtime edits, service restart or build is authorized by this documentation synchronization. Historical receipts remain preserved below; current contract and deployed acceptance are distinct.


Owner correction on 2026-10-09 supersedes the Reception-specific client entry
and workspace proposals below. Ordinary client login UI/UX remains unchanged.
The server resolves username/password through PACS first, then Reception after
credential rejection, then checks local grants. Windows/Android owners are
removing the added sign-in UI and wiring automatic memory-only exchange. The
latest ordered-resolution/startup check passed 30 guards. Source parity was
reopened for this correction; no activation or build qualification is claimed.

## Single Send report orchestration � 2026-10-09

Report authoring uses one Send action in Windows and Android. Normal company
report requests retain modality/template/profile, while the server tries Turbo
first then the native company service on upstream failure/empty output. Personal
API never enters company fallback. Report-only client timeout is 480 seconds;
no timeout replay is added. Legacy Turbo requests are compatibility aliases and
Turbo is hidden from advertised workflows. Attached reports return a clear error
if fallback cannot consume attachments. Thirteen targeted server guards pass;
Windows final report/timeout owner suite passes 92. Native GUI, real provider
fallback and iOS authoritative-source acceptance remain pending.

## Shared AI connection and speech continuation � 2026-10-09

One approved Eagle Eye connection supplies company imaging, EchoMind, Secretary
and CRM; ordinary login and per-user grants remain mandatory. Personal direct API
requires own credentials and explicit prompt. Windows/mobile settings review is
coordinated with their owners. Voice defaults to Auto: Google, GapGPT Whisper,
then company speech. Android recorded-file Google is not currently implemented;
its continuation uses the new authenticated `/v1/speech/transcribe` contract.
Server speech requires the relevant EchoMind/Secretary/CRM grant and license,
keeps credentials server-only, bounds audio/concurrency and returns redacted
errors. Seventeen speech/HTTP synthetic guards pass. Native provider acceptance,
iOS implementation/access and controlled activation remain pending.

## Mandatory human identity and local grants — 2026-10-09

The source now requires both PACS-or-Reception identity verification and local
Eagle Eye approval on protected HTTP requests. Pairing and licensing remain
independent gates. New identities are pending by default; Server User settings
manage EchoMind, imaging/module, CRM and Secretary grants and audit history.
The local console administrator is not a third remote identity provider.
See [protocol and provider limitations](USER_AUTH_PROTOCOL.md).

The paired-device bypass guard failed before the change (202 instead of 401).
Earlier local security/startup snapshot passed 142 tests under offscreen Qt. The
legacy HTTP/TLS/CRM/Secretary integration suite passes 134 tests. The inactive
Razi user-auth snapshot passes 138 security/identity/startup guards; its four
settings GUI guards were verified locally. Earlier Android debug build and 289 JVM tests
passed; client corrections require new receipts. iOS has no verified executable Mac
access and remains unimplemented. The earlier Windows explicit Reception-only entry has been removed.
Latest server identity/startup verification passes 106 tests.

Candidate `20261009-user-auth` preserves the executing baseline; initial staging
matched all 76 changed files. Expanded reconciliation additionally preserves the
completed Education source changes (210 tests, one existing xfail) and the reviewed
Secretary supplement (94 tests, one existing xfail). Final source-inventory
verification is recorded in the private staging receipt. Required payload parity,
live upstream/GUI acceptance and controlled activation remain separate gates;
complete Developer parity and build handoff are not claimed. Source changes are
not active on Razi. Legacy sender-usage statements below describe historical
behavior; new /v1/usage is per-user v2 counts/events, not v1 device token summaries.

## Server console identity — 2026-10-09

Server-only console authentication and same-host deployment are documented in
[SERVER_CONSOLE_AUTH.md](SERVER_CONSOLE_AUTH.md). Local private administrator
provisioning succeeded on both hosts; 21 local and 17 staged Razi synthetic guards
pass. Candidate 20261009-server-console-auth has hash-verified changed files.
No live source GUI pass,
Razi activation or complete Developer parity is claimed. Observed SCM selects
20261009-education-presenter with its CRM-restoration runtime. Pre-existing
local/active server and Secretary differences remain unresolved.

**Owner workflow (2026-10-09):** server function tests run on the synchronized Razi
Developer source; local Client integration and both product builds run on the
control computer after acceptance. [Standing workflow](DEVELOPER_TEST_BUILD_WORKFLOW.md).
The same-host former Client entitlement has received official signed Server-role
provisioning, with Client state preserved. Active revision and transition outcome
are determined by the fresh private activation receipt, not the older milestones below.

**Server sender usage (2026-10-08):** usage rows and filtering identify the
authenticated paired client. Human login usernames are not yet recorded.
178 local guards pass, including separate HTTP requests for all 29 functions.
These use synthetic outputs; active-service HTTP 404 and live GUI remain open.
See the latest usage follow-up in the settings record.

**Usage breakdown (2026-10-08):** named module/function rows replace aggregate-only
UI metrics in Eagle Eye, EchoMind and Agent. 143 local guards pass; live GUI and
activation remain pending. See the latest follow-up in the settings record.

**AI usage (2026-10-08):** each functional AI tab shows retained server request
and reported token counters. 106 local guards pass; live GUI remains pending.
See the usage follow-up in [the settings record](CLIENT_AI_CONNECTION_SETTINGS_2026-10-08.md).

**Connection simplification (2026-10-08):** embedded MCP/mobile advanced controls
are collapsed; the Server PACS preset reuses the active local profile in a worker.
104 focused and 19 gateway-wiring local guards pass. Live GUI remains pending.
See [the current settings record](CLIENT_AI_CONNECTION_SETTINGS_2026-10-08.md#follow-up-simplified-embedded-control-and-colocated-pacs).

**Client settings update (2026-10-08):** AI > Connection consolidates existing
connection controls on Standard Client only; Server layout is preserved. Local
100 focused guards pass; live GUI remains pending. See [scope and acceptance](CLIENT_AI_CONNECTION_SETTINGS_2026-10-08.md).

**Mandatory owner rule (2026-10-08):** every change on either Developer host must
be reconciled and synchronized to the other in the same work session. Completion
and build handoff require hash-verified parity; blocked sync remains a blocker.
See [Developer synchronization policy](DEVELOPER_SYNC_POLICY.md).

## Latest Developer reconciliation — 2026-10-08

The complete non-running `20261008-reconciled-developer/source` candidate selects
the reviewed local source and adds guarded PortAudio/native-runtime fixes. Both
Breast and Bone complete synthetic inference passed on Razi. The active SCM still
uses r4; independent server licensing, live GUI and activation remain pending.
See [reconciliation and build handoff](SOURCE_PARITY_RECONCILIATION_2026-10-08.md).
The following audit records the state before reconciliation.

## Latest source parity audit — 2026-10-08

Active Razi SCM uses `20261008-lumbar-marrow-r4/source`. Local and active Razi
Developer sources are not identical: 138 runtime content differences and 74
local-only runtime files. No build or synchronization occurred in this audit.
See [source parity evidence and required reconciliation](SOURCE_PARITY_AUDIT_2026-10-08.md).
Older dated checkpoints below are historical, not the current active-source selector.

October 6 follow-up: recoverable correction toolbar and native labelmap import are
implemented; 53 guards pass and native voxel roundtrip is exact. GUI save/server
apply remains pending while preserving reported unsaved edits. See HISTORY.md.

## 2026-10-06: Client manual brain review path fix

The source client stages the Slicer entry script outside space-containing checkout
paths and stores private review sessions under `AI_DIR/eagle_eye/manual-reviews`.
Live Slicer loaded the reference image and anatomical segments with the Segment
Editor source volume selected. Fifty focused guards passed. The authenticated
server advertises brain correction support. Export and the complete live server
revision roundtrip remain pending; capabilities alone are not acceptance. The
already-running PACS process must load the updated source before testing its
Apply button. See [history](HISTORY.md#2026-10-06-slicer-manual-review-launch-and-path-compatibility).

## 2026-09-30: Current Developer service with hosted EchoMind

The active SCM source is `revisions/20260930-echomind/source`, Python 3.13.5,
using `config/server-20260930-echomind.json`, LocalService and existing paired TLS
port 8002. PACS/CRM are unchanged. All 15 real synthetic EchoMind calls passed;
94 target guards passed. Fresh GUI ping/action discovery works; full workflow
acceptance remains open. App-local software Slicer startup/hidden warm-up passed
on a separate current-native copy, not a System32 replacement. See
[current source, receipts and remaining gates](ECHOMIND_SERVER_2026-09-30.md).
Older port/source inventories below are historical, not active routing guidance.

## 2026-09-27: MS multi-sequence source candidate

Cross-plane 2D FLAIR support and optional matching 3D pre/post-T1 subtraction review are implemented. Local private inference and PDF verification passed; fresh native GUI and versioned Razi activation remain pending. No automated enhancement classification is supplied. See [method and evidence](MS_MULTISEQUENCE_2026-09-27.md).

## 2026-09-26: Smooth-band follow-up (source candidate)

MS-only native 2D paired-band separation is implemented with raw/retained/amber review masks and PDF provenance. Related automated gate: 157 passed; 472 mirrors match. Thresholds remain exploratory, not clinically qualified. The fresh source test bridge responds, but new native GUI acceptance and Razi activation are pending. Earlier unfiltered 2D acceptance does not close these gates. See [method and evidence](LESIONS_2D_2026-09-26.md#reversible-smooth-band-review-follow-up).

## 2026-09-26: Native 2D lesion pilot

See [2D lesion development and evidence](LESIONS_2D_2026-09-26.md). Local source GUI, isolated Razi inference and the authenticated Razi service/API run passed. The service completed in 160.85 s with an identical native mask. Customer redistribution and clinical qualification remain pending. Earlier dated inventory below is historical.


**Full UI update:** [Full workstation deployment](FULL_WORKSTATION.md) records the
complete source, dedicated environment and interactive launch. Human sign-in passed,
but the subsequent source GUI workflow FAILED with a native Advanced fault.

**Latest:** [Independent service acceptance](SERVICE_AUTH.md) adds a LocalService
SCM candidate on 8043 with automatic startup and tested recovery. The inventory
below describes the preserved 8042 task, which was not replaced.

Status checked on 2026-09-23: task running and listener bound to127.0.0.1:8042.
Read-only refresh also confirmed the selected source and VC143 Slicer in deployment.json.
Other evidence below is dated pilot evidence, not continuous monitoring.

| Item | Installed location or state |
|---|---|
| Workspace | D:/Eagle Eye Server |
| Active source | revisions/20260923-dev/source |
| Main environment | runtime/Scripts/python.exe; Python3.13.3, isolated venv |
| Current Slicer | slicer/20260923-vc143-candidate |
| Configuration | config/server.json; config/pilot.token is private |
| Data/logs | jobs/ and logs/ |
| Manual launch | Start-EagleEye.ps1 starts task AI-PACS Eagle Eye Development |
| Task action | Run-EagleEye.ps1 runs tools/eagle_eye/serve.py with explicit config |
| Current scheduling | One computation by default, per-client quota1 |
| Inactive extraction | revisions/20260923-pilot is incomplete; never execute it |
| Historical native runtime | slicer/20260923; fails native startup on Razi |
| Historical runner | Run-EagleEye.before-vc143.ps1; selects that failing runtime |
| Transfer evidence | revisions/20260923-dev/transfer-manifest.json; incoming archive |
| Native correction receipt | logs/slicer-vc143-candidate-receipt.json |

Dependencies installed offline in the dedicated environment: requests2.34.0,
pydicom2.4.5, numpy2.4.4, PySide6 6.10.2, SimpleITK2.5.3 and their wheel dependencies.
pip check passed. The canonical workstation uses Python3.13.5; do not claim complete
environment parity. Model runtimes require their own versions and packages.

The task uses the existing administrator user's S4U token with limited run level.
It has no boot trigger. It survives the SSH session, but is not the final least-
privilege service design. Shared Python and global Visual C++ runtimes were not changed.

## Network roles

| Port | Role | Status |
|---|---|---|
|105|PACS DICOM|Existing clinical listener; preserve|
|50052|PACS socket protocol|Separate metadata/download path; preserve|
|8000|Local PACS API|Required study lookup route observed|
|8002|Legacy Breast API|Still active; not replaced|
|8042|Eagle Eye development API|Loopback only; credentials required|
|8770|Reception CRM|Existing clinical listener; preserve|

PACS source URL is http://127.0.0.1:8000. allowed_roots is currently empty, so
clinical source staging cannot succeed. No remote clinical inference has passed.
The VM has32GB RAM; about8.3GB was free at the earlier pilot sampling. Refresh capacity
before workloads. Heavy Brain execution is not authorized by that capacity evidence.
Windows firewall profiles were observed disabled during preflight; do not rely on
rule scoping as active protection. No LAN HTTP listener was opened for this pilot.

2026-09-27 picker follow-up: local acquisition selector fixes the inaccessible second 2D FLAIR choice; 2 fail-before guards and 64 pass-after tests. Native GUI pending. See MS_MULTISEQUENCE_2026-09-27.md.

2026-09-27 characterization follow-up: source now adds same-T1 anatomical locations and an exploratory tissue-calibrated focal-increase screen, preserving explicit boundary/coverage uncertainty. 145 automated passes; private PDF inspected. Native GUI, Razi activation and clinical validation remain pending. See MS_MULTISEQUENCE_2026-09-27.md.

- 2026-09-27: Three-color FLAIR component agreement and separate exploratory pre-contrast T1 evidence added; see MS_MULTISEQUENCE_2026-09-27.md. Automated suite 147 passed; refreshed-source GUI and Razi activation pending.

- 2026-09-27: Patient PDF references use scientific citations; T1 hypointensity interpretation distinguishes persistent injury-associated signal from single-scan findings. See MS_MULTISEQUENCE_2026-09-27.md.

- 2026-09-27: Shared brain PDF readability updated (sentence breaks, 135% leading, paragraph spacing); 25 focused tests passed and 25-page lesion artifact visually checked.

- 2026-09-27: Shared PDF readability verified for volumetry, lower-limb Alignment and Total Spine; legacy brain path unified and Total Spine methods/references reorganized. 53 focused guards pass; synthetic artifacts inspected.

October 6 saved-results follow-up: background exact-study report recovery and review controls implemented; 95 focused guards pass. Two existing private PDFs recovered. Fresh source GUI, unsaved-edit preservation and live correction submission remain pending. See HISTORY.md.

October 6 saved review follow-up: result-owned dialog routing replaces viewport-dependent open; compact PDF/review controls and sticky errors added. 98 focused passes and synthetic layout inspection; fresh source GUI and live correction return pending. See HISTORY.md.

October 6 sidebar follow-up: local exact-study brain result availability now contributes to the red Eagle Eye indicator; 33 targeted guards pass. Source GUI verification pending. See HISTORY.md.

October 6 inline editor follow-up: floating correction popup/toolbar superseded by controls embedded in native Segment Editor for new sessions. 53 guards and real Slicer widget-parent probe pass; full source GUI/save/server return pending. Preserve existing unsaved sessions.


October 6 packaging follow-up: fixed missing Nuitka physical manual-correction script. 71 focused guards pass; distribution staging has 19 passes and 3 existing EchoMind mirror failures. Full source GUI and second-PC installer acceptance remain pending; see HISTORY.md next-build checklist.


## 2026-10-07: Patient case synchronization staged, activation pending

Candidate 20261007-case-realtime is based on active 20261004-secretary-help-ticket.
It adds authenticated same-center case/history reads and PACS invalidation bridging.
Eighty target tests and pip check pass; 16 overlay files have verified hashes.
The prior service remains active and has no case_realtime capability. Local
Patient/case selection has 59 passes; adjacent server/TLS has 45 passes.
Restricted config and prior SCM command are backed up. Activation helper verifies
ownership, hashes and empty queues and restores the prior command on failed
post-start acceptance. Manual approval and actual Patient red availability/saved
result retrieval/second-client GUI acceptance are pending. No PACS/CRM restart,
model replacement, installer, clinical qualification or activation is claimed.
Receipts: validation/case-realtime-20261007-stage.json; immutable prior revision.

## 2026-10-07: Razi Eagle Eye case synchronization activated

Owner-approved activation completed. AIPacsEagleEye runs 20261007-case-realtime
under LocalService with existing private configuration. Authenticated paired-TLS
acceptance passed: protocol 1, case_realtime enabled, seven model routes and
fourteen EchoMind workflows. PACS 50052/8000, DICOM 105 and CRM 8770 retained
prior process owners. Restricted rollback backup and prior baseline are retained.
Receipt: validation/case-realtime-20261007-cutover.json (activated=true).
Actual Patient red availability, saved-result retrieval and second-client GUI
acceptance remain pending. Eighty candidate tests passed before activation.

## 2026-10-07: Echocardiography and reference review activated

Razi AIPacsEagleEye now runs `20261007-echo-reference-r2`, derived from the
active case-realtime baseline. It adds the ECHOCARDIOGRAPHY Report/Turbo prompt
and server-owned `add_reference` workflow. Registry 2026-10-07.2 provides
INTERGROWTH fetal centiles and ASE adult echo limits; missing context and
unsupported parameters remain unclassified. Signed unsupported values (GLS)
remain in the review. It is a measurement review, not automatic clinical grading.

The target passed 28 reference/history and 22 adjacent case/TLS tests; pip check
passed. Four actual-provider synthetic examples passed. Authenticated activation
retained seven model routes, case synchronization and 15 EchoMind workflows;
PACS, DICOM and CRM listener owners were unchanged. Workstation-to-Razi requests
for echo reports and both reference families passed; the final request confirmed
registry .2 and retained negative GLS. Restricted rollback configuration/SCM
backup and immutable prior source are retained. Receipts are server validation/
reference-r2-20261007-stage.json, reference-r2-20261007-provider.json and
reference-r2-20261007-cutover.json. Actual fresh-source client GUI and reception
export acceptance remain pending. No installer or full clinical qualification.
See docs/echomind/REFERENCE_REPORTS.md in the canonical workstation repository.

## 2026-10-08: Lumbar marrow Development pilot

Canonical source adds the Lumbar Bone Marrow experimental T1 function, bounded
remote module and server-owned signal draft. Whole-vertebra erosion is explicitly
not validated marrow/body segmentation or red marrow fraction. New guards: 24;
adjacent: 219 plus five scheduler; builder/runtime: 56, two frozen-stage skips.
Razi r3 server guards: 48 passes (one client-menu deselection and one rerun);
pip check passes. 515 plugin mirror pairs match.

Owner authorized a separate Development route. Revision 20261008-lumbar-marrow-r3
runs through the manual-only AI-PACS Lumbar Marrow Development 20261008 task,
existing Supervisor ownership, isolated job root, paired TLS loopback 8042 and
an authenticated workstation SSH tunnel on 18042. Capabilities advertise the new
module. Shared AIPacsEagleEye SCM path/state are verified preserved. No firewall
change occurred. Automatic review rejected the initial direct LAN/firewall command
with blocked by policy; the loopback alternative succeeded. No PHI in this record.
Source GUI, actual patient/model inference and clinical qualification remain open.
See docs/modules/LUMBAR_BONE_MARROW.md in the canonical repository. Server receipts:
marrow-stage.json, marrow-tests-server.json, marrow-development-task.json and
marrow-transition-plan.json in the r3 revision. No production cutover or installer.

Actual portable-model preflight passed on Razi: full manifest/file/weight hashes,
TotalSegmentator import and PyTorch 2.6.0+cpu, status ready. One network attempt
was blocked by the existing audit guard. Inference explicitly was not executed.
Receipt: validation/marrow-preflight-20261008/result.json. Human-run source
launcher: tools/eagle_eye/open_marrow_development.ps1 in the canonical repository.

## Shared Razi activation 2026-10-08
Owner explicitly requested the existing server update. The shared AIPacsEagleEye
service now uses the hash-verified 20261008-lumbar-marrow-r3 candidate and unchanged
paired HTTPS8002 configuration. All durable client jobs were terminal before restart.
Authenticated normal workstation capabilities advertise lumbar-marrow and eight routes;
jobs API succeeded. Exact SCM/config backup: server backups/marrow-service-20261008.
Initial sc.exe update failed and restored baseline; structured CIM Change succeeded.
Real patient inference and GUI acceptance remain pending; experimental measurements
are not clinically qualified. Normal clients require no tunnel/config change.

## Review UX, PDF and Slicer revisions 2026-10-08
The report-only browser caused cramped numeric cells and poor image navigation.
MarrowReview now separates Image and measurements, Structured report and Physician
notes. The scrollable/pannable preview has Fit, Zoom and 100% controls. Measurement
cells use two decimals, volume in cm3, fixed readable header spacing and level colors
matching the existing overlay palette. Colors identify anatomy, not severity.
Definitions explain arbitrary SI, ROI, mean/median/SD and QC. Physician notes are
included in the exported draft but do not overwrite server measurements.
PDF uses the existing Eagle Eye paged A4 renderer with marrow title/footer; synthetic
PDF was rendered with bundled Poppler and visually checked. No patient artifact
was copied into documentation. Source identity unavailable is explicit, not invented.
Slicer uses existing isolated prepare_review/manual_slicer controls. Server now
exports owned reference image, full labelmap and label names. Saved edits use the
bounded label correction protocol: same source/owner/parent, mask hash, geometry,
allowed labels, size/decompression limits and revision-conflict checks. Signal
remeasurement occurs only on the server without rerunning inference; original job
is retained. Interrupted submissions retain a resumable client handle. Earlier
results without review assets require a new analysis. Corrected labels are whole
vertebrae followed by the same 2 mm erosion, not a validated marrow-body segmentation.
Razi scoped R4 candidate is active on the existing paired HTTPS8002 service. The
all-client durable queue was idle; exact prior SCM/config backup is on server at
backups/marrow-review-20261008. Normal client capabilities confirm marrow analysis
and correction. Candidate synthetic guards:22 passed,1 old client-menu deselected.
Canonical tests and UI/PDF synthetic checks pass; fresh source GUI/Slicer/native
patient correction acceptance pending. No installed Client or full build was created.
515 mirrors match; no affected plugin mirror. Client PyInstaller/Nuitka package
whole ai_imaging; server correction source is included in existing full-core tree.
Rollback: after queue drain restore prior SCM binpath from activation receipt and
start only AIPacsEagleEye; revert client review changes separately if necessary.


## Reception CRM source candidate (2026-10-08)

AI > CRM and CRM connection attachment are implemented with a bounded owned child and the shared company AI gateway. The source imports CRM 1.32.6 and all ten latest prompts; existing live CRM/Eagle Eye services remain unchanged. GUI, protected state migration and frozen/activated service acceptance are pending. See CRM_INTEGRATION_2026-10-08.md.

## Shared connection presentation - 2026-10-09

See SHARED_AI_CONNECTION_2026-10-09.md. Backend, Company Authentication and
EchoMind/Eagle Eye/Agent usage now share the server Connection hub. Five focused
settings guards pass locally. Private service configuration binding, remote
snapshot parity and native GUI/provider acceptance remain pending; no activation.

Eagle AI Brain naming correction: Server 1 - GapGPT selects the existing company backend; models/prompts remain unchanged. Local settings tests: 5 passed. Razi activation and native acceptance remain pending.

Shared Brain accounting update: private Server 1 center-code administration and per-source upstream call/token ledger implemented. 88 focused local guards passed. Dental request-usage fixture fails separately. Razi source staging, complete parity, activation and native/provider acceptance remain separate gates. See SHARED_AI_CONNECTION_2026-10-09.md.

Brain authority update: shared company identity now gates hosted provider calls and CRM diagnostics; see BRAIN_AUTHORITY_2026-10-09.md and BRAIN_DEPLOYMENT_GATE_2026-10-09.md. Active clinical service is unchanged; complete parity/native/provider acceptance block activation.

Four Brain routes: LLM G/A/V and Custom API implemented; see BRAIN_PROFILES_2026-10-09.md. V100 public LLM API port awaits owner input; A/V have no qualified inference adapter. Custom API chat-completions only; native/provider acceptance and full parity pending.

## Current-request narrative language source (2026-10-10)

Secretary now scopes language per original request, accepts optional fa/en preference and negotiates old-server compatibility. The local combined Secretary/helper guards pass 110 tests. CRM source readiness is authorized separately; its known worker timeout remains unresolved. See [contract and qualification limits](REQUEST_LANGUAGE_2026-10-10.md). Full local/Razi parity, activation and native/provider acceptance remain pending.

## Private admission/drain source (2026-10-10)

Inactive canonical source now counts HTTP work through completion and model Futures through cleanup, rejects new work while draining, resumes on a busy drain budget and commits cooperative close only at known zero. The private child handshake prevents unsupported commands reaching an old child. The scoped suite passes 164 tests. [Contract](SAFE_TRANSITION_2026-10-10.md). Old-active bootstrap, full parity, CRM worker acceptance and live administrator integration remain blocked/pending; no service was changed.


## Lumbar marrow full-volume candidate — 2026-10-11

Current development delta: see [implementation and acceptance gates](LUMBAR_MARROW_MULTISEQUENCE_2026-10-11.md). Canonical implementation and isolated Razi calculation pass; active source parity, authenticated route and live result-tab acceptance remain pending.


### Marrow input protocol 2 (2026-10-12)

Required sagittal T1/T2 and Dixon in/opposed-phase; STIR and multi-echo optional.
Unique editable automatic suggestions, descriptive signal-drop fallback, native
signal features and corrected-mask recalculation implemented. 44 focused guards
pass; live GUI, full Developer parity and authenticated Razi activation remain
pending. See LUMBAR_MARROW_MULTISEQUENCE_2026-10-11.md, protocol 2 section.
