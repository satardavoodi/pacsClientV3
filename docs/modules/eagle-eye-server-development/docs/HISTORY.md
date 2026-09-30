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
