# Execution backlog

## 2026-10-12: Option 1 activation gates

- Verify scoped Chat routing and Custom Assist/Search guards.
- Stage reviewed changes on Razi without changing executing source.
- Reconcile full Developer inventory before build; overlay hashes alone are insufficient.
- Record live Chat and Custom unavailable acceptance separately.

## Shared connection and speech qualification � 2026-10-09

- Accept one paired AI connection across imaging, EchoMind, Secretary and CRM;
  separately verify user/module denial and account/profile invalidation.
- Accept own-key plus own-prompt personal mode without silent company routing.
- Verify fresh/default speech Auto and preservation of explicit saved choices.
- Accept Android live Google and authenticated recorded-file continuation on the
  source-matched server; recorded-file Google is currently unavailable, not passed.
- Validate server speech credential provisioning, actual Whisper/company behavior,
  quality rejection, bounded audio, permission/license denial and no timeout replay.
- Qualify iOS on its authoritative Mac source; access remains a prerequisite.

## Human access qualification — 2026-10-09

- Complete source parity and synthetic tests in a new inactive Razi revision;
  preserve all remote-only changes and block build handoff until full parity.
- Accept real PACS and Reception login, upstream rejection, disabled local user,
  module denial, logout/account switch and per-user history in source GUIs.
- Verify Reception compiled/source parity and immediate account-deactivation
  behavior; current token verifier does not check Deactive.
- Record Windows, Android and iOS integration/build acceptance independently.
- Provision access-store ACLs for the actual console and service identities and
  configure only the installed same-host identity providers before activation.
- Authenticated HTTP fixtures now use explicit synthetic upstream identities and
  real local approval; 134 legacy guards pass. Keep the real-authority security
  guards separate; no production compatibility bypass is permitted.

## Server console authentication — 2026-10-09

Private provisioning and immutable Razi candidate staging are complete. Complete
candidate activation, full source
parity and human source-GUI acceptance for [the Server-only login](SERVER_CONSOLE_AUTH.md).
Follow with password rotation/recovery, durable lockout and idle/session locking.
Keep Standard Client offline behavior and independent PACS/reception access intact.

October 6 follow-up: recoverable correction toolbar and native labelmap import are
implemented; 53 guards pass and native voxel roundtrip is exact. GUI save/server
apply remains pending while preserving reported unsaved edits. See HISTORY.md.

## 2026-10-06: Manual brain correction acceptance

Source launch/path fixes and 50 focused guards pass. Real Slicer image and
segmentation loading passed. Finish explicit Save correction export, verify
geometry and label identity, then submit the revision through the authenticated
server and verify the returned PDF. Repeat the client button workflow in a fresh
source process; the current process predates the fix. Do not overwrite the
original analysis or claim a capability response proves revision completion.

## 2026-09-30: Current acceptance priorities

Use [the current checkpoint](ECHOMIND_SERVER_2026-09-30.md), not old 8042/8043
deployment paths. EchoMind code and actual paired synthetic API gate pass.
Complete fresh source GUI report/assist/template rendering, all model inference,
client edits/export and recovery. Native software startup/warm-up passes;
rendered study acceptance is separate. Preserve the owner's deferred Breast
classification limitation. Build Server installers only after Developer gates;
do not infer readiness from capability names or payload hashes.

## MS multi-sequence acceptance (2026-09-27)

Complete native source GUI selection/run/export acceptance and a scoped versioned Razi service/API/artifact pass. Review sensitivity of cross-plane thresholds, slice gaps, smooth-band handling and residual T1 intensity bias. Enhancement remains unclassified; qualify any new classifier separately. See [method and evidence](MS_MULTISEQUENCE_2026-09-27.md).

## Smooth-band follow-up acceptance (2026-09-26)

Source implementation and 157 automated tests complete. Complete fresh native GUI run/export, clinician review of retained and separated candidates, scoped versioned Razi candidate/API acceptance, and separate installer/clinical qualification. Preserve small lesions and explicitly evaluate false negatives; one exploratory case cannot set universal normal-signal thresholds. See [2D owner record](LESIONS_2D_2026-09-26.md#reversible-smooth-band-review-follow-up).

## 2026-09-26: Native 2D lesion pilot

See [2D lesion development and evidence](LESIONS_2D_2026-09-26.md). Local source GUI, isolated Razi inference and the authenticated Razi service/API run passed. The service completed in 160.85 s with an identical native mask. Customer redistribution and clinical qualification remain pending. Earlier dated inventory below is historical.


This is the local execution view of the existing Eagle Eye Server/Client plan and
OPT-51, not a separate architecture roadmap. Update state and evidence as work completes.

| ID | Work | Owner | State / completion evidence |
|---|---|---|---|
|D1|Dedicated source environment and authenticated loopback API|Eagle Eye|Verified pilot|
|D2|New custom Slicer target startup with app-local CRT|Build|Synthetic startup verified; clinical models separate|
|D3|Graceful owned stop/drain and no orphan listener|Eagle Eye|Empty SCM stop/recovery verified on 8043; loaded drain and original task gap open|
|D4|Complete reviewed source/import closure and isolated model assets|Eagle Eye|Full UI source/environment plus 126,380 model payload files verified; full service-source binding and target inference unqualified|
|D5|Authoritative local PACS storage/authentication mapping|Eagle Eye + Unify|Open; allowed_roots remains empty|
|D6|Uncached acquisition, cache leases and completion manifests|Unify producer / Eagle Eye consumer|Open; use existing handoff|
|D7|Measured CPU/RAM/disk/GPU admission and module readiness|Eagle Eye|Open; capability names are insufficient|
|D8|Razi Bone Age and Breast detection, then remaining models|Eagle Eye|Open; resource and source gates first|
|D9|Transactional queue recovery, attempts and result publication|Eagle Eye|Open; restart currently interrupts work|
|D10|Client recovery UI, native result acceptance|Client/Eagle Eye|API resume exists; UI acceptance open|
|D11|Production listener limits/TLS, protected config, retention/backup|Server|Open; pilot is loopback over SSH|
|D12|SCM service/account/reboot/update/installer parity|Server + Build|LocalService installed; recovery verified; reboot, real account and installer gates open|
|D13|Replace legacy8002 and qualify updated clients/rollback|Server + Client|Not performed; requires prior acceptance|
|D14|Interactive annotation revisions and recomputation|Client + Server|Phase two|
|D15|Breast stacked-classifier feature compatibility/optimization|Breast|Deferred by owner; never label classification ready|

## Immediate acceptance blocker

The full-workstation source GUI gate failed after human sign-in on Razi. Diagnose
the session-scoped Advanced SetInputData native fault with the Viewer owner and
Home Reception-breaker stall with the shared UI owner before repeating viewer
acceptance. DICOM receipt exists, but successful rendering is not certified.
Do not patch another owner's runtime, change its feature flags or relaunch a
crashed clinical-source UI without the documented owner/human workflow.
See [full-workstation evidence](FULL_WORKSTATION.md).

See [service acceptance](SERVICE_AUTH.md) for completed D3/D12 work. Next are
real-account/UI acceptance, pilot consolidation, D4/D5 and actual model tests.
Build owner continues shared CRT/cache parity independently. Do not make native
packaging edits in parallel with that workstream or copy another task's unfinished
assets. Do not promote to8002 merely because the API or Slicer startup responds.

2026-09-27 characterization follow-up: source now adds same-T1 anatomical locations and an exploratory tissue-calibrated focal-increase screen, preserving explicit boundary/coverage uncertainty. 145 automated passes; private PDF inspected. Native GUI, Razi activation and clinical validation remain pending. See MS_MULTISEQUENCE_2026-09-27.md.

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

## 2026-10-08 reconciliation acceptance

- Provision the independent signed Server license before controlled activation.
- Complete existing MCP/live source GUI acceptance after human launch/login.
- Repair the wider diagnostic suite failures without client-direct company-provider fallback.
- Run remaining model and frozen-build acceptance through BUILD.md/RELEASE.md.
- Select the reconciled revision explicitly during activation; the running r4 service is unchanged.

See [reconciliation](SOURCE_PARITY_RECONCILIATION_2026-10-08.md).


## CRM acceptance and completion (2026-10-08)

Complete live source CRM sign-in/question workflow; migrate private reception configuration and authoritative service conversations across Windows service identities; expose original history, attachments, reports and prompt administration; add CRM usage rows, cancellation and concurrent progress; measure combined imaging/EchoMind/CRM load before enforcing fair CPU/RAM/GPU budgets. Verify both frozen backends before controlled service activation and rollback. See CRM_INTEGRATION_2026-10-08.md.

- Shared AI Connection: finish authenticated private-provider configuration binding,
  complete endpoint inventory, reconcile the Razi immutable candidate and perform
  native GUI/provider acceptance. See SHARED_AI_CONNECTION_2026-10-09.md.

Eagle AI Brain naming correction: Server 1 - GapGPT selects the existing company backend; models/prompts remain unchanged. Local settings tests: 5 passed. Razi activation and native acceptance remain pending.

Shared Brain accounting update: private Server 1 center-code administration and per-source upstream call/token ledger implemented. 88 focused local guards passed. Dental request-usage fixture fails separately. Razi source staging, complete parity, activation and native/provider acceptance remain separate gates. See SHARED_AI_CONNECTION_2026-10-09.md.

Brain authority update: shared company identity now gates hosted provider calls and CRM diagnostics; see BRAIN_AUTHORITY_2026-10-09.md and BRAIN_DEPLOYMENT_GATE_2026-10-09.md. Active clinical service is unchanged; complete parity/native/provider acceptance block activation.

Four Brain routes: LLM G/A/V and Custom API implemented; see BRAIN_PROFILES_2026-10-09.md. V100 public LLM API port awaits owner input; A/V have no qualified inference adapter. Custom API chat-completions only; native/provider acceptance and full parity pending.

## Current-request language qualification (2026-10-10)

- Reconcile the scoped language delta into an immutable Razi candidate and verify complete Developer parity.
- Resolve the known CRM worker startup/read timeout without masking it.
- Accept generated fa/en responses for Secretary, Office/CRM and PACS on both authoritative mobile platforms and the affected Windows GUI.
- Keep activation/build handoff blocked until the existing drain, parity and acceptance gates pass. See [contract](REQUEST_LANGUAGE_2026-10-10.md).

## Private safe transition qualification (2026-10-10)

- Independently prove old-active ordinary-human-r2 drain; inactive counters cannot prove it. Never probe its stdin with new JSON commands.
- Reconcile complete immutable source/payload inventories before first transition.
- Resolve CRM worker acceptance and qualify private owning-service administrator integration with real concurrent work.
- Keep legacy SCM stop/parent-loss/desktop close distinct from the qualified transition API. See [contract](SAFE_TRANSITION_2026-10-10.md).


## Lumbar marrow full-volume candidate — 2026-10-11

Pending qualification: see [implementation and acceptance gates](LUMBAR_MARROW_MULTISEQUENCE_2026-10-11.md). Canonical implementation and isolated Razi calculation pass; active source parity, authenticated route and live result-tab acceptance remain pending.


### Marrow input protocol 2 (2026-10-12)

Required sagittal T1/T2 and Dixon in/opposed-phase; STIR and multi-echo optional.
Unique editable automatic suggestions, descriptive signal-drop fallback, native
signal features and corrected-mask recalculation implemented. 44 focused guards
pass; live GUI, full Developer parity and authenticated Razi activation remain
pending. See LUMBAR_MARROW_MULTISEQUENCE_2026-10-11.md, protocol 2 section.
