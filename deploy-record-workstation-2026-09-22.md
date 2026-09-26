# Deployment Safety Record — workstation — 2026-09-22

**Change:** AI-PACS 3.6.7 Advanced MPR warm-up path and native Slicer UI build parity.
**Gate result:** BLOCKED
**Deployment performed:** No.

**Client build result (completed 2026-09-23):** The canonical isolated
`--local-install-qa --target client` workflow completed for Standard and
x64-on-ARM64-emulated in both PyInstaller and Nuitka. The coordinator status is
`completed`, both backends exited 0, and the cross-backend coherence check
exited 0. This is installation-QA evidence only: the checkout remains dirty,
the source was not published, distribution approval is false, and the earlier
Git receipt is expired.

**Deeper local inventory and recovery:** Visual Studio 2022 Build Tools provides
MSVC 14.44 and CMake 3.31.6. The repository contains the custom Slicer source
plus an assembled runtime, but no prior SuperBuild tree or Qt 5.15.2 SDK was
found in the related project, build-snapshot, archive, or standard installation
locations checked. The separately installed stock Slicer 5.8.1 is not the
custom project build and has no Qt development headers/configuration. The
pinned Qt 5.15.2 SDK was installed in `C:\Qt`, the exact pinned
Slicer/custom-utilities sources were recovered, and the current custom app was
built under `C:\S\NB`. The assembled Developer Run runtime, immutable Client
asset cache, PyInstaller stage, and Nuitka stage all contain the same new inner
viewer binary SHA-256
`275B7FC209DE41A1610FF0105762F2090B428621640FD43F406FC16ECF62874E`
and startup bridge SHA-256
`FA83AFF5C5F0CC7D1D31E94E7CA929D6AA54A498B702A38B47ACA81F2F7EFD86`.
This does not clear the deployment gate.

**Canonical local installer evidence:**

- PyInstaller Standard: 627,196,743 bytes;
  SHA-256 `9D2C9945AD30AC4DB1C6FE3A07AEA8AD95570BA8E14021AEAF019EB149483907`.
- PyInstaller ARM64-emulated: 627,196,913 bytes;
  SHA-256 `868C040A114AB3C9A008127968CAA79B38C8DE675B806A4671CC91C72E8D998F`.
- Nuitka Standard: 609,307,527 bytes;
  SHA-256 `5FF5F7462E25F34ABC5B139AD120B22F3A93BF6BE4A8C18B5412DF0E686C6B2F`.
- Nuitka ARM64-emulated: 609,307,587 bytes;
  SHA-256 `6D9889770049057A058B45630E7D118003CE6D14025115164956F08F2700417A`.

## Workstation

- [ ] BLOCKED — Clinical behavior preserved — No fresh source and installed candidate GUI workflow acceptance after these changes. Verify patient open, study/series navigation, Advanced MPR explicit open, hidden warm-up, and clinical tools on a clean test installation.
- [ ] BLOCKED — Viewer features intact — Overlays, measurements, reference lines, sidebars, sync, and thumbnails have not all been exercised in the rebuilt installed candidate.
- [–] N/A — FAST mode safe — This change does not modify FAST rendering or instantiate VTK windows; a normal release smoke test remains part of the clinical gate above.
- [ ] BLOCKED — Metadata and DICOM handling preserved — Automated packaging tests do not establish installed cross-study identity or DICOM workflow acceptance.
- [ ] BLOCKED — Tests and log review — The 11 focused native/cache guards pass, 470 plugin mirror pairs match, both isolated stages pass sanitized-config and eight-package checks, and build coherence passes. The repository-wide builder lane reports 214 passes plus one failure caused by the deliberately stale checkout-local stage; the exact isolated candidate stage passes that same parity check. Source/installed GUI acceptance and relevant session log review have not occurred. The local Test Control Server was unavailable.
- [ ] BLOCKED — Rollback plan — The prior same-version Nuitka Client outputs and metadata are preserved under `builder nuitka/output/installer/_superseded/2026-09-23-pre-native-slicer-r1`, but a clean-host rollback trial is not recorded.
- [–] N/A — Performance change does not disable functionality — The current correction is a build-integrity gate, not a performance optimization; warm-up timing is not claimed.

## Cross-project

- [–] N/A — API/data boundary documented — No website or remote API contract changes in this build-integrity correction.
- [x] CONFIRMED — Data ownership documented — `BUILD.md` and `builder/docs/ADVANCED_MPR_BUILD_RUNTIME_INTEGRATION.md` distinguish source, assembled runtime, immutable cache, package payload, and per-user installation.
- [ ] BLOCKED — Privacy/PHI reviewed — No patient data was used in the synthetic guards, but the repository readiness report still records credential-shaped source/history and release security coordination is outstanding.
- [ ] BLOCKED — Manual approval before production — No explicit approval of a rebuilt and tested installer has been given.

## Blocking items

1. Publish and synchronize the exact reviewed source commit through `RELEASE.md`, then create a promotable candidate from its fresh Git synchronization receipt. The completed local install-QA candidate is not a substitute for this gate.
2. Complete source and clean-host installed GUI checks, including hidden warm-up without an unsolicited Slicer window and the current customized Slicer UI after an explicit Advanced MPR open.
3. Complete the remaining clinical workflow checks, private log review, clean-host rollback evidence, and credential remediation.
4. Obtain explicit owner approval for production promotion after the preceding evidence is reviewed.

## Sign-off

Manual approval given by: NOT YET GIVEN.
