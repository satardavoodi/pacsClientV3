# Decisions and history

## 2026-10-09: One Send action; server-owned report fallback

Remove separate report Turbo controls from Windows/mobile. Company Send submits
one normal report; server tries existing Turbo/ChatGPT first, then native company
LLM once on upstream error/timeout/empty output. Preserve modality/template/profile,
user grants, history/request identity and personal API isolation. Capability
metadata advertises report with `report_policy=turbo_then_company`; legacy Turbo
requests remain compatibility aliases. Attached reports fail explicitly if the
native fallback cannot consume their attachments. Live acceptance is separate.

## 2026-10-09: Shared AI connection and separate speech routing

One approved Eagle Eye Server address/port/pairing serves company imaging,
EchoMind, Secretary and CRM with per-user/module authorization. Personal direct
API remains an own-credentials plus own-prompt option. Voice to Text is a separate
exception: default Auto orders Google, GapGPT Whisper, then company speech.
Ordinary client login is unchanged; connection success does not grant modules.

## 2026-10-09: Preserve ordinary client login; server resolves authority

Owner clarified that Windows, Android and iOS retain their existing login UI/UX.
No provider choice or separate Eagle Eye login is added. The first protected
request exchanges the current logged-in user's credentials automatically. Eagle
Eye tries PACS first, then Reception after credential rejection, and checks its
local grants only after identity resolution. A local denial never falls through
to another identity provider. CRM workflow credentials do not replace the current
AI principal. Earlier Reception-specific entry/workspace proposals are superseded.

## 2026-10-09: Two independent human access gates

Owner requires each Windows/mobile sender to have a signed-in PACS or Reception
user. Eagle Eye verifies that upstream identity and independently checks its own
user/module grants before proceeding. Either configured provider suffices; no
local-only remote identity is allowed. Credentials are exchanged transiently for
an opaque device-bound, expiring process-local user session; upstream verification
and local grants are checked again on protected requests. No password is persisted
or repeated on every inference request. User approvals and request audit metadata
live in an Eagle Eye-owned SQLite database separate from clinical MongoDB.

Windows, mobile and CRM conversations received the owner-authorized protocol and
implementation requests. Reception fixed-route adapter uses primary JavaScript
contract evidence; token-time Deactive enforcement and compiled parity remain
unverified. No production service transition or build is implied.

Combined verification: 142 local security/startup guards and 134 legacy HTTP/TLS/
CRM/Secretary guards pass; the inactive Razi candidate passes 138 security guards.
The Secretary owner reviewed a 39-file supplement and repaired its stale snapshot
hash receipt. Completed Education source was reconciled against the remote source:
no remote-only Python definitions or documentation headings were discarded; local
cover-fit/zoom/navigation updates retain their 210 passing tests and one existing
xfail. Only source, tests, docs and mirrors are staged; course content databases,
patient files, credentials and host configuration are excluded. These source checks
do not qualify production model payloads, GUI acceptance or iOS.

## 2026-10-09: Server console administrator and same-host architecture

Owner specifies co-installed Reception, PACS Server and Eagle Eye Server.
Server console must reject unauthenticated offline access and use its own
privately provisioned superadministrator. Client offline behavior is unchanged.
The local verifier uses salted PBKDF2 and Windows user-bound DPAPI, never an
embedded password. See [scope, gates and deployment](SERVER_CONSOLE_AUTH.md).
No service restart, release build or full parity claim accompanies this slice.

## 2026-09-30: EchoMind moved to the Eagle Eye service

Added a headless server-owned prompt core and strict text endpoint; removed the
client's legacy PACS login route and repaired Turbo Correction modality context.
Versioned Developer cutover retains paired TLS 8002, LocalService, PACS/CRM and
immutable baseline. 252 local/94 target guards passed; all 15 real synthetic
client requests passed. Current-native app-local Mesa startup/hidden warm-up
passed; human-authorized GUI launched with explicit TestServer and existing
bridge responds. Full model/GUI, rollback drill and installer gates remain open.
See [the checkpoint](ECHOMIND_SERVER_2026-09-30.md).

## 2026-09-27: Independent FLAIR support and contrast review

Added optional second 2D FLAIR and matching 3D post-T1 roles, reference-only remote transport, acquired-slab corroboration, preserved disagreement masks, normalized subtraction review and PDF panels. Real local inference and synthetic tests passed. No server activation, installer or clinical qualification was performed. See [method and evidence](MS_MULTISEQUENCE_2026-09-27.md).

## 2026-09-26: Reversible periventricular band review

Added a source candidate for conservative MS-only smooth paired-band separation on native axial 2D FLAIR. Raw mask and suspected-band mask remain downloadable; PDF distinguishes red retained candidates and amber review bands. Manual revisions bypass the classifier; MS-to-SVD restores raw measurements. 157 related tests and 472 mirror pairs passed. No clinical normality claim, model replacement, 3D change, new installer or Razi activation is implied. Fresh GUI and clinical review remain separate gates; see the 2D owner record.

## 2026-09-26: Native 2D lesion pilot

See [2D lesion development and evidence](LESIONS_2D_2026-09-26.md). Local source GUI, isolated Razi inference and the authenticated Razi service/API run passed. The service completed in 160.85 s with an identical native mask. Customer redistribution and clinical qualification remain pending. Earlier dated inventory below is historical.


## 2026-09-23 service and authentication follow-up

Installed an independent LocalService SCM candidate on 8043. Empty stop/start and
automatic failure recovery passed; delayed boot start is configured. Added encrypted
PACS account renewal and a shared settings console. The proposed 8042 replacement
was rejected by automatic approval review and did not execute. Original task and
clinical services remain unchanged. See [the acceptance record](SERVICE_AUTH.md).

## 2026-09-23

- Owner selected D:/Eagle Eye Server for source development on Razi Reception.
- Created isolated venv using existing Python3.13.3; installed reviewed offline
  main-runtime wheels without altering shared Python. Source differs from the
  canonical workstation's Python3.13.5 and requires explicit model qualification.
- First extraction hit long Windows paths. Moved complete Slicer into a short
  independent runtime path; kept incomplete extraction inactive.
- Verified8,096 transferred files. API pilot initially died with SSH disconnect;
  changed to a manual-only scheduled task independent of SSH. No boot trigger.
- Authenticated API and actual remote Client through SSH passed. Clinical8002,
  PACS105/8000 and CRM8770 retained their existing processes.
- New native VTK failed with1114/0xC0000142 on Razi in both Session0 and1. A separate
  probe using official VC14314.44 DLLs succeeded. Build owner prepared a new candidate
  preserving7,836 originals and adding10 app-local CRT files. No System32 changes.
- Ordinary launcher and headless script passed. Activated corrected candidate
  after empty-queue verification and retained prior runtime/runner. Client retest passed.
- Scheduled-task stop left its Python listener alive; stopped only the verified
  empty pilot listener after exact command-line ownership check. This remains D3.
- Build owner updated canonical Developer Run and immutable all-role cache to the
  VC143 baseline:34,459 files /4,309,450,168 bytes, full verification and parity passed.
  Existing installers were not rebuilt and release_approved remains false.
- Added this local documentation set, including current-state, operations, code map,
  tests and open work. Documentation installation does not restart the API.

## Decision record

Source development is preferred for the pilot; frozen installation is a subsequent
acceptance lane. Slicer stays precompiled and versioned separately. One repository
and shared contracts serve both editions; client UI is independent of service life.
Legacy Breast remains active until explicit tested cutover. Source references,
not client DICOM uploads, define phase-one analysis. Breast optimization is deferred.

Control-repository references (not relative links in this remote export):
docs/plans/architecture/EAGLE_EYE_SERVER_CLIENT_PLAN_2026-09-21.md;
docs/OPTIMIZATION_STABILITY_RELIABILITY_MASTER_PLAN.md (OPT-51);
docs/release-and-build/SLICER_NATIVE_BASELINE_2026-09-23.md;
BUILD.md; RELEASE.md; docs/plans/architecture/REGRESSION_CATALOG.md.

Workstream coordination: Eagle Eye task owns server runtime/pilot; task titled
Evaluate Git Push and Build owns native Slicer and packaging. Source and assets
contain uncommitted work; a historical Git SHA alone cannot reproduce this pilot.


## Full workstation source acceptance, 2026-09-23

Transferred 5,525 verified full-runtime source files and installed a dedicated
workstation environment. Added root source launchers and a manual interactive
Server task; retained the independent SCM service and legacy processes. Human
sign-in succeeded. A subsequent Home freeze and native Advanced access violation
failed the UI gate. Read-only inspection confirmed 128 MR DICOMs reached the local
cache; completeness and rendering are not certified. Breast/Bone Age private
Python homes were relocated, and Bone Age required ten verified app-local CRT
libraries for successful imports. Model inference remains unqualified.
The full-workstation document records exact paths, receipts and remaining gates.

2026-09-27 picker follow-up: local acquisition selector fixes the inaccessible second 2D FLAIR choice; 2 fail-before guards and 64 pass-after tests. Native GUI pending. See MS_MULTISEQUENCE_2026-09-27.md.

2026-09-27 characterization follow-up: source now adds same-T1 anatomical locations and an exploratory tissue-calibrated focal-increase screen, preserving explicit boundary/coverage uncertainty. 145 automated passes; private PDF inspected. Native GUI, Razi activation and clinical validation remain pending. See MS_MULTISEQUENCE_2026-09-27.md.

- 2026-09-27: Three-color FLAIR component agreement and separate exploratory pre-contrast T1 evidence added; see MS_MULTISEQUENCE_2026-09-27.md. Automated suite 147 passed; refreshed-source GUI and Razi activation pending.

- 2026-09-27: Patient PDF references use scientific citations; T1 hypointensity interpretation distinguishes persistent injury-associated signal from single-scan findings. See MS_MULTISEQUENCE_2026-09-27.md.

- 2026-09-27: Shared brain PDF readability updated (sentence breaks, 135% leading, paragraph spacing); 25 focused tests passed and 25-page lesion artifact visually checked.

- 2026-09-27: Shared PDF readability verified for volumetry, lower-limb Alignment and Total Spine; legacy brain path unified and Total Spine methods/references reorganized. 53 focused guards pass; synthetic artifacts inspected.


### 2026-10-06: Slicer manual-review launch and path compatibility
A live remote brain review had valid matching reference/label images but no editor. The manual launch passed a space-containing source path through CTK; unlike the existing viewer launch it did not stage the script. After staging application code to a private temporary directory, live startup exposed a second error: Slicer's bundled Python could not read the deeply nested review session path. Sessions now live under `AI_DIR/eagle_eye/manual-reviews/<uuid>` while retaining the full original result, parent server job and original-mask hash. Original analysis artifacts are unchanged. Launcher output is captured privately in the session. The staged script path uses a Windows short path if TEMP has spaces, otherwise fails explicitly when unsupported.

A launch regression failed before the patch. Focused manual-review, remote correction and builder guards: 50 passed. Remote tests cover corrected-label transport, parent identity and geometry, capability checks and child-result conflicts; this is not a live production correction receipt. A fresh real Slicer launch logged successful loading of both reference volume and label volume after the two fixes. Native editor acceptance passed: the reference image and anatomical segments are visible in three orthogonal views and the Segment Editor source volume is selected. Export and production apply acceptance remain pending; the user is interacting with the editor and the save panel is no longer exposed. The authenticated server advertises brain corrections. The live Slicer log also contains an existing nonfatal MaskVolumeEffect decimalsOption compatibility error; this optional effect was not repaired or qualified by this launch fix. No deployed server changes or release performed. Global mirror verification reported unrelated EchoMind ai_chat_pages drift; it was not synchronized.


### 2026-10-06: Recoverable manual-save dialog and labelmap import (OPT-51)
The user could dismiss the only correction dialog, leaving only Slicer's general
scene Save action. A persistent AI-PACS correction toolbar now reopens that same
owned nonmodal dialog. Save displays a busy label and prevents repeated clicks.
The existing server-only correction transport and original inference remain intact.

The former loader expanded each region into a full-volume array and inserted each
separately. Native shared-labelmap import now runs once, with rendering suspended
and node notifications batched. Sparse original label values are verified before
editing; empty lesion masks remain editable. This uses Slicer's documented
ImportLabelmapToSegmentationNode API (developer-guide segmentations), not a change
to anatomical measurement or inference.

Two new guards failed before implementation (missing recoverable controls/native
import seams); the final focused manual/remote/builder suite has 53 passes, exit 0.
The actual bundled Slicer, no-main-window same-process before/after probe on the
original 98-label input measured import 3.865 s versus 0.901 s; extraction 3.488 s.
Every voxel matched after extraction. A synthetic 32-label probe also matched
(0.511 s versus 0.287 s). These timings exclude process startup and visible render
cost; they do not establish total user-visible latency. Private receipts stay in
C:/Temp/ee-manual-native[-full]-probe.json and contain aggregate timings only.

Fresh source GUI close/reopen/save and server Apply acceptance remain pending.
The user reports unsaved edits; do not close or replace that session. No targetable
Slicer window was present in the current desktop inventory. The PACS test-control
bridge is unavailable. Existing nonfatal MaskVolumeEffect compatibility warning
is outside this fix. Mirror check: one unrelated EchoMind drift out of 512; untouched.
Client-side manual editor source is the changed build input; the authenticated
Server correction implementation is unchanged. No installer was built or verified.
Rollback is limited to these manual_slicer.py controls/import changes; preserve the
prior path fix and all other dirty work. Next candidate must exercise reopen/save
and parent-bound server revision on its exact built artifact.


### 2026-10-06: Persistent study-bound brain result review
Brain workspaces now include Saved Brain Results, with background discovery and
refresh, original/manual revision labels, and an action to reopen the report and
correction controls without inference. Choosing Brain tools in another workspace
also installs the tab. Discovery reads only exact hashed-study directories and
owned matching manual-review sessions. Conflicting study UIDs, foreign paths and
artifact-directory mismatches are rejected. Saved corrections can be reapplied;
active analysis or manual sessions cannot be replaced by selecting history.

The guard failed before adding the discovery service. Final targeted suite:
95 passed, exit 0 (manual review, saved results, remote revisions, workspace entry,
result tabs and brain payload). Native import timing is recorded above. Read-only
private discovery returned two PDFs for the source study and included its original
result; no new inference or server revision was submitted. Native source GUI and
full Slicer-save/server-apply remain pending. The current desktop lacks a targetable
Slicer window despite reported unsaved edits; those edits must be located/preserved
before closing or replacing any user session. The source test bridge is unavailable.
No installed artifact or deployment acceptance is claimed. Mirror verification still
has only the unrelated EchoMind drift. New history files belong to the existing
ai_imaging source package, not a new model or feature flag.


### 2026-10-06: Saved report open action and compact review UI follow-up
The user reported an oversized saved-results list and a flashing status with no
review window. Controlled reproductions exposed two faults: archived review
entered input-series selection (and could fail without a viewport), and discovery
refresh replaced its error message. The exact exception in the user's already
running instance was not captured; do not equate synthetic evidence with that trace.

Saved review now owns one nonmodal dialog per artifact directory, validates study
identity before construction, and re-shows an existing dialog without reloading its
result or replacing unsaved corrections. It never needs selected_series_uid or
starts inference. The existing new-analysis sessions are separate and unchanged.
Teardown cancels owned review work. The saved list is a bounded-width card with
48-pixel rows, 230-320-pixel list height and compact adjacent PDF/review/refresh
buttons. Open PDF uses the selected worker-validated artifact directly. Refresh
retains open errors; diagnostic logs contain exception type and function/line
frames only. A click during background discovery is queued with its selected path.

Two added guards failed before the fix. Final related suites: 98 passed, exit 0.
The callback test opens/reopens an actual Qt dialog with a deliberately unavailable
viewport and verifies unsaved-session retention. A synthetic offscreen layout was
rendered and inspected, but this is not the required live PACS GUI pass. The source
bridge ping is unavailable; user requested to launch fresh source -TestServer after
preserving clinical edits. Live GUI, Slicer-save/server-apply and packaged artifact
acceptance remain pending. Mirror check still reports only unrelated EchoMind drift
(1/512); no global sync, release or deployment performed. Roll back only this
saved-results UI/controller follow-up if needed, preserving earlier path/import fixes.


### 2026-10-06: Local brain report availability in Patient sidebar
The sidebar controller previously used only the live server inventory; downloaded
brain report discovery used a separate local inventory, so a saved report could
exist without a red Eagle Eye indicator. PatientCaseController now checks the
existing exact-study local brain inventory on its worker, at most every ten seconds.
Local availability and server availability remain distinct; a server disconnect
cannot erase verified local report availability. Changing case clears local state,
and delayed results are applied only to their captured patient/study binding.
When only local brain results are available, clicking Eagle Eye selects Saved Brain
Results in the owned workspace without submitting analysis. EchoMind behavior is
unchanged. Tests inject the local finder and never read the clinical DB or files.

Two guards failed before the new seam existed. Final sidebar/workflow/history/case
suite: 33 passed, exit 0; covers local-only red state, disconnect retention, case
switch clearing, stale completion rejection and saved-tab navigation. Existing
mirror check still has one unrelated EchoMind drift out of 512. No release or
server deployment. Live source indicator verification for the reported examination
is pending: the current Test Control Server is unavailable. Do not claim that the
already-running app has loaded this change. This is client UI availability only,
not a new model or inference route. Keep the existing server access checks intact.


### 2026-10-06: Inline native Segment Editor correction controls
Owner requested removal of the floating correction popup. manual_slicer.py now
parents a plain QWidget to the native Segment Editor module and inserts it at
layout index zero. Paint/Erase/Draw target the currently selected existing segment;
the same controls cover volumetry and lesion masks. Save and its success/error
status are inline. The former floating QDialog and reopen toolbar are removed for
new review sessions. Label identity, geometry validation, original preservation
and server revision transport are unchanged. Existing live sessions are not
reparented or restarted, preserving any unsaved clinical edits.

Two revised guards failed before implementation. Focused manual/remote/payload
suite: 53 passed, exit 0. An isolated bundled Slicer probe instantiated the real
Segment Editor module widget and verified index zero and isWindow()==False;
receipt C:/Temp/ee-embedded-review-probe.json. This native widget check is not a
full clinical source GUI save/server-apply acceptance. That gate and installer
artifact acceptance remain pending. Mirror check remains one unrelated EchoMind
drift out of 512. No generated Slicer build files, server deployment or installer
were changed. This supersedes the earlier floating popup/toolbar UI decision.


### 2026-10-06: Manual correction UI next-build portability

- Found a backend-specific packaging defect: PyInstaller app_a_datas already ships the physical manual_slicer.py, but Nuitka OPTIONAL_DATA omitted it. Added the script to the shared Nuitka spec consumed by the staged release command. The external Slicer interpreter cannot use only a frozen Python import.
- Guard test_both_builders_ship_native_manual_correction_script failed before the fix and passes afterward. Customer-path, manual-review, default Eagle Eye inclusion and release-candidate packaging suites: 71 passed (exit 0). Distribution-profile suite: 19 passed, 3 failed; all three failures are the existing EchoMind source/mirror mismatch, not Slicer retention. Preserve that workstream's in-progress files.
- Applicability: Standard Client and ARM64-emulated Client retain the custom Slicer runtime without local inference model payloads; PyInstaller and Nuitka both ship the correction script. Eagle Eye Server uses the same workstation script input where its UI is installed. Inference and corrected-mask recalculation remain server-owned; the panel and editing are client-owned. No new flag, dependency, installer component or native Slicer rebuild is introduced.
- Next build MUST use BUILD.md and its isolated candidate workflow after release prerequisites are satisfied. Check the installed modules/ai_imaging/eagle_eye_brain/manual_slicer.py hash against the exact candidate source. Ensure newly added saved_results.py and saved_results_widget.py are included through modules.ai_imaging collection. Existing installers have not changed.
- Artifact acceptance pending: on another PC without this development checkout, in normal operation, retrieve a saved brain result, load source image and all segments, verify the correction panel is embedded (no floating popup), exercise Paint/Erase/Draw, save correction, apply mask on server and reopen the revised report. Verify both volumetry and lesion editing, DPI/layout usability and writable user-data paths. Preserve unsaved sessions. TEMP paths containing spaces require a working Windows short-path alias under the current launcher workaround; test this explicitly before calling portability complete.
- Source full GUI/save/server roundtrip and actual installer/second-PC acceptance remain pending. The earlier native Slicer parent/layout probe verifies embedding only. No installer was built or deployed in this change.


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

Final local verification: 260 passed, two frozen-stage checks skipped (no build); 513 plugin mirror pairs matched.

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

## 2026-10-08: Complete Developer source reconciliation

Reviewed all 201 historical content differences and staged the complete source/resource closure in the non-running reconciled revision. Optional PortAudio import and isolated Breast native-runtime fixes passed targeted guards. Bone weight selection matches the authoritative A100 source. Both model synthetic smokes pass on Razi. See [full evidence and remaining acceptance](SOURCE_PARITY_RECONCILIATION_2026-10-08.md). Active SCM remains r4; licensing and GUI acceptance are pending.

## 2026-10-08: Mandatory two-way Developer parity

The owner requires all changes from either host to be reconciled and applied to
the other in the same work session. Local and Razi AGENTS entry points now enforce
this completion/build gate. See [the contract](DEVELOPER_SYNC_POLICY.md). Host
private state and running-service activation remain distinct.

## 2026-10-08: Client shared AI Connection page

Client-only fourth AI subtab now hosts existing connection controls from EchoMind,
Eagle Eye and Agent. Server keeps its original page layout. Local focused gate: 100
passed; live GUI acceptance pending human source launch/MCP attachment. See
[scope and verification](CLIENT_AI_CONNECTION_SETTINGS_2026-10-08.md).

## 2026-10-08: Simplified embedded MCP/mobile and local PACS settings

Connection uses collapsed advanced pairing/network controls. Embedded MCP is
read-only; mobile pairing uses the existing gateway. Server PACS presets read
the active profile in a worker without saving/migrating settings. Four guards
failed before the change; 104 focused and 19 gateway wiring guards pass locally.
[Scope and limitations](CLIENT_AI_CONNECTION_SETTINGS_2026-10-08.md#follow-up-simplified-embedded-control-and-colocated-pacs).


## 2026-10-08: retained AI usage panels

Owner-scoped shared usage endpoint and worker-backed panels were added to Eagle
Eye, EchoMind and Agent. Unknown tokens and unavailable histories stay explicit.
106 local guards pass; staged source parity and GUI/runtime activation are distinct.
See CLIENT_AI_CONNECTION_SETTINGS_2026-10-08.md for scope and limits.


## 2026-10-08: named usage breakdown

Per-module/workflow/Agent-function rows now show separate request and token
counters. Canonical catalogs, owner isolation and unknown values are guarded.
143 local passes; source Developer synchronization does not activate r4.


## 2026-10-08: authenticated sender usage and request matrix

Server usage now separates client/function rows with a cached client selector.
178 local guards pass, including all 29 function dispatches for two authenticated
synthetic clients, failed usage and rejected spoofing. Human user attribution,
active service activation and live GUI remain separate open gates.


### 2026-10-08: Automatically restore separate brain result tabs

Opening the workspace discovered only results with server_module; legacy brain results without that field remained hidden until explicit Brain selection exposed the history widget. Discovery now recognizes the existing brain analysis_type / posterior_rows / manual_rows / normative contracts when server_module is absent. Exact-study and artifact ownership checks remain mandatory. Brain Volumetry and Brain Lesions each receive their own saved-result tab and a Review / correct segmentation action. The first restored brain tab is selected only while the user remains on Imaging Tools; a user-selected tab is preserved and repeated restoration does not duplicate tabs. No analysis is submitted by restoration.

Two synthetic regressions failed before the change; 43 discovery/history/workspace tests pass after it (exit 0). All 517 plugin mirror pairs match. Runtime sources are collected through modules.ai_imaging in both backend builds; no new dependency, component or flag. Applies to Client Standard/ARM and workstation-enabled Server; no headless inference change. Live source GUI remains pending because the documented control listener is unavailable. Next artifact acceptance: open an exact-study case with both saved result types without Choose Function, verify both tabs, PDF access and correction, and verify another study does not inherit them. No build or service activation was performed. Developer parity receipt is recorded separately; pending parity prohibits completion/build handoff.


### 2026-10-08: Saved report reader contrast and readability

Print HTML inherited a dark QTextBrowser base, leaving dark report text unreadable. The client reader now uses white paper, dark text, a 24-pixel document margin, minimum 11-point text, 135% line spacing and paragraph spacing. Clinical text, alignment and explicit warning colors remain intact. PDF and correction actions move to a top action row with text zoom controls. No stored HTML/PDF or measured values are changed. A synthetic dark-palette regression fails before and passes after; 44 local history/workspace guards pass. A synthetic Qt rendering was inspected with the system Segoe UI font registered for the offscreen renderer. Full source GUI acceptance remains pending: control listener unavailable. Runtime/test changes synchronized to the inactive Razi Developer candidate; concurrent documentation/source deltas still block full parity and build handoff. Both builders collect the existing module; no dependency/component added.


### 2026-10-08: Compact saved report layout and section navigation

The saved-report page now centers a maximum 1120-logical-pixel reading column instead of stretching tables across the display. The column shrinks with the available layout. A Report section selector navigates existing level-1/2 headings without changing clinical content. Short PDF action keeps the top bar compact. Extended behavioral guard failed before the change; 44 local saved-result/workspace guards pass afterward. Runtime/test delta is hash-checked against the inactive Razi Developer candidate before synchronization; full parity remains blocked by the previously recorded concurrent documentation changes. Live GUI and installed artifact acceptance remain pending. Existing modules.ai_imaging collection covers both builders; no added dependency or flag.


### 2026-10-08: Shared client brain report presentation standard

The saved client report reader is shared by Brain Volumetry and Brain Lesions, including small-vessel/white-matter and MS contexts. No context-specific duplicate renderer is needed. Standard: centered 1120px maximum reading column, light report paper, minimum 11pt text, 135% line height, section navigation, zoom, PDF action and correction action. Clinical headings, numerical content, reference limitations and warning colors remain report-owned. This standard concerns client presentation; it does not rewrite stored PDFs or change disease classification. Three parameterized context guards exercise the same restored page and correction binding. The focused history/reader suite passes 14 tests locally. Live source GUI and complete Developer parity remain pending under the existing recorded blockers; no activation or build.


### 2026-10-08: Breast classification and calcium delivery (B93)

The normal Breast adapter now starts server-owned tissue and calcium branches.
The existing corrected classifier bundle resolves the active r4 schema mismatch;
no classifier weight or threshold changed. The calcium result is source-bound in
the authenticated envelope, persisted per detection run and loaded asynchronously
into a separate client overlay. Branch completion is explicit in the dialog.
MONOCHROME1 polarity/padding handling has synthetic equivalent-pixel guards and
retains research-only qualification. The earlier sealed candidate is preserved.
See docs/modules/breast-ai/B93_DUAL_RESULT_DELIVERY_2026-10-08.md in the workstation
root for evidence, failed attempts and pending gates. Active r4 is not modified.


### 2026-10-08: Reference position labels beside brain measurements

Numeric regional volume cells now show Below/Above reference or Below/At/Above median when the reference supplies a median. Values outside available bounds are red; this supersedes the previous >25% display threshold, not a clinical diagnosis. Shared cells cover medial temporal measurements too. Atlas analogues remain unclassified. No exact percentile is invented from endpoints. WMH keeps its separate approximate age/sex curve band and explicitly marks bands wholly beyond P5-P95; method uncertainty remains visible. Five position guards failed before and 48 focused guards pass after. Reference loading on the active service remains unresolved; these labels do not repair unavailable tables. Private comparison of two independently tagged original 3D acquisitions used existing results, not new inference: full rows are in a private local CSV, not repository fixtures. Full GUI, document parity and active-service activation remain pending.


## Hosted reception CRM source integration (2026-10-08)

Verified CRM 1.32.6 against the installed server receipt, compared every prompt and retained newer assess/interpretation prompts. Imported the existing brain instead of rewriting it. Added shared-pairing client/UI, private configuration attachment, reception-session ownership and a server-owned read-only process. Worker smoke uncovered and corrected missing PDFium/Mongo dependencies, virtualenv child PID ownership and HTTPStatus transport. Developer parity, automated tests, live GUI and active service state are separate gates; see CRM_INTEGRATION_2026-10-08.md.

## 2026-10-09: Developer test/build ownership and former Client role migration

Recorded the standing Razi function-test/local integration/local dual-product-build
workflow in AGENTS.md, CLAUDE.md and the synchronization runbook. Diagnosis: the
existing valid legacy Client license was not a signed Server entitlement. Official
same-device internal Developer Server issuance is bounded by existing verified
remaining whole-day validity; Client state is preserved and no runtime guard is
weakened. Private receipts track role provisioning and controlled activation
separately from full function/GUI/build acceptance. No release build is requested.

## 2026-10-09: Secretary content assets (source candidate)

Added shared end-user course edits, public research/download/image delivery and complete PACS course imports. See `docs/agent_control/SECRETARY_CONTENT_WEB_ASSETS_2026-10-09.md` in the full source snapshot. Default static retrieval; optional Playwright and administrator-configured image provider. No production activation or live acceptance claimed.

- 2026-10-09: Added the server shared Connection presentation foundation;
  details and unresolved provider/configuration boundaries are recorded in
  SHARED_AI_CONNECTION_2026-10-09.md. No backend activation or release qualification.

Eagle AI Brain naming correction: Server 1 - GapGPT selects the existing company backend; models/prompts remain unchanged. Local settings tests: 5 passed. Razi activation and native acceptance remain pending.

Shared Brain accounting update: private Server 1 center-code administration and per-source upstream call/token ledger implemented. 88 focused local guards passed. Dental request-usage fixture fails separately. Razi source staging, complete parity, activation and native/provider acceptance remain separate gates. See SHARED_AI_CONNECTION_2026-10-09.md.

Brain authority update: shared company identity now gates hosted provider calls and CRM diagnostics; see BRAIN_AUTHORITY_2026-10-09.md and BRAIN_DEPLOYMENT_GATE_2026-10-09.md. Active clinical service is unchanged; complete parity/native/provider acceptance block activation.

Four Brain routes: LLM G/A/V and Custom API implemented; see BRAIN_PROFILES_2026-10-09.md. V100 public LLM API port awaits owner input; A/V have no qualified inference adapter. Custom API chat-completions only; native/provider acceptance and full parity pending.

## 2026-10-10: Preserve Client behavior during server migration

The owner requires the latest Windows Client prompts, model selectors, templates,
study context and command instructions to survive migration to Eagle Eye Server.
Do not replace models or change clinical prompt policy to make synthetic examples
pass. Existing native Assistant/Search routes and next-day Agent acceptance are
outside this repair slice.

The report Send worker lost its previous Turbo study-profile forwarding; the
worker fix and regression are recorded in
`docs/echomind/REPORT_MIGRATION_PARITY_2026-10-10.md`. Existing normal-finding
generation instructions are preserved; response wording variability alone is not
evidence of changed prompts.

The active Developer export retained fourteen engine source files but omitted
the complete model bindings. Read-only resolution failed for eight advertised
imaging modules. Restore complete approved model directories in a NEW immutable
source revision, including the Brain parent runtime probe and shared Alignment
runtime dependency; never copy only runners/weights or modify executing source.
Verify full manifest hashes using extended Windows paths before binding. Local
and Razi runtime layouts may differ; source and weight identity must match.

The protected acceptance and model-integrity receipts are retained under
`generated-files/eagle-eye/activation-20261010` and the corresponding Razi staging
directory. Source/model parity, activation, inference and native GUI acceptance
are separate gates. No release build or clinical qualification is implied.

## 2026-10-10: Current-request narrative language

The original current request determines Persian/English response language; positive explicit targets win and ambiguous input uses the selected preference. Machine schemas and authority remain unchanged. Secretary legacy requests remain accepted, new preferences are negotiated, and deterministic narrative/errors follow the scoped selection. Local helper/Secretary suite: 110 passed. No Razi activation, full parity or live provider/native acceptance is claimed. See [contract](REQUEST_LANGUAGE_2026-10-10.md).

## 2026-10-10: Private admission and cooperative transition

Added process-local inflight accounting, bounded drain with automatic abort/resume, sticky uncertain-completion refusal and zero-only cooperative commit. Model leases outlive HTTP202 until Future cleanup. Private owning-parent control requires an explicit new-child handshake and correlated zero receipt plus successful process exit. Synthetic scoped suite: 164 passed. Existing emergency stop semantics remain separate; old-active bootstrap and full Developer parity are not solved by new counters. No activation. See [contract](SAFE_TRANSITION_2026-10-10.md).


## Lumbar marrow full-volume candidate — 2026-10-11

Development record: see [implementation and acceptance gates](LUMBAR_MARROW_MULTISEQUENCE_2026-10-11.md). Canonical implementation and isolated Razi calculation pass; active source parity, authenticated route and live result-tab acceptance remain pending.


### Marrow input protocol 2 (2026-10-12)

Required sagittal T1/T2 and Dixon in/opposed-phase; STIR and multi-echo optional.
Unique editable automatic suggestions, descriptive signal-drop fallback, native
signal features and corrected-mask recalculation implemented. 44 focused guards
pass; live GUI, full Developer parity and authenticated Razi activation remain
pending. See LUMBAR_MARROW_MULTISEQUENCE_2026-10-11.md, protocol 2 section.
