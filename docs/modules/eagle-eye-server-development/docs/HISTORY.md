# Decisions and history

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
