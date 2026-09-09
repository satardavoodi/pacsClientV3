# Deployment Safety Record — AI-PACS workstation — 2026-09-06

**Change:** Fresh local 3.6.5 PyInstaller and Nuitka candidate for Eagle Eye,
Standard, and Windows-on-ARM64 emulation editions.

**Gate result:** LOCAL BUILD COMPLETE; BLOCKED FOR PRODUCTION DISTRIBUTION

## Verified build evidence

- Candidate `C:\b\365r15` completed both backends and cross-backend coherence with
  exit code 0. It was not published and has not received production acceptance.
- Six installers were written to the existing backend installer folders. Their
  independent SHA-256 calculations match the generated metadata and checksum
  lists, and every installer reports FileVersion and ProductVersion 3.6.5.
- Standard and ARM retain Advanced MPR/Slicer while excluding the Eagle Eye-only
  offline lumbar model. Eagle Eye contains Slicer and the declared model.
- The PyInstaller TOC and Nuitka report include the cardiac Flow DICOM
  VM-normalization and DICOMDIR modules. The relevant focused verification passed
  111 tests with direct pytest exit code 0.
- Codec discovery metadata is present in the Nuitka report. Both staged cores pass
  the Qt/ICU hygiene checks, and both backend builds completed the Lite Viewer
  self-test.
- EULA, third-party notices, installation notes, release metadata, and SHA-256
  lists were generated through the established repository structure.
- `BUILD.md` is now the single human/AI build entry point. It records the measured
  r15 bottlenecks, separates fast disposable validation from the full release
  matrix, fixes the six filenames and two output folders, and forbids unsafe
  parallelism, stale reuse, Slicer removal, and automatic executable launch.
- The exact pre-build selection documented in `BUILD.md` passed 114 tests. The
  focused runbook/packaging boundary passed 46 tests. The wider builder suite
  passed 150 tests and retained one known failure against the development
  checkout's stale generated `builder/output/stage` configuration. The isolated
  r15 candidate passed its fresh stage parity gate; generated output was not edited
  to mask the checkout-local failure.

## Production blockers

1. All six installers are unsigned. Sign only after candidate approval, then
   regenerate and independently verify the manifests and SHA-256 lists.
2. Install, upgrade, uninstall, and rollback have not been exercised on an
   isolated clean Windows workstation.
3. The ARM package is x64-on-ARM64 emulation and still requires validation on real
   Windows-on-ARM64 hardware.
4. A representative authorized de-identified cardiac Flow export still requires
   clinical re-import and quantification acceptance in cvi42 or the target external
   workstation. Automated packaging and VM-normalization checks are not a substitute.
5. Installed clinical workflows, logs, viewer behavior, and privacy boundaries
   require acceptance testing.
6. Credential revocation/rotation, runtime secret loading, repository-history
   remediation, and secret-scanning controls from the readiness audit remain open.
7. Qt and complete third-party license compliance require legal confirmation.
8. Inno's admin-install/per-user-data warning requires clean-install policy review.
9. Explicit owner approval is required before any upload or customer distribution.

## Sign-off

Manual production approval given by: NOT YET GIVEN
