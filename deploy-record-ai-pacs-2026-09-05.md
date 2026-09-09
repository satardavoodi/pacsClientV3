# Deployment Safety Record — AI-PACS workstation — 2026-09-05

**Change:** Local 3.6.5 PyInstaller and Nuitka installer readiness for Eagle Eye, Standard, and Windows-on-ARM64 emulation editions, including cardiac Flow export, codec licensing, legal payload, and offline license protection.
**Gate result:** BLOCKED for production distribution

The corrected 3.6.5 installer set completed on 2026-09-05. Standard and ARM now
retain the standard Advanced MPR/Slicer runtime, all six installer metadata
records show 3.6.5, the Information panel follows the running application
version, and the PyInstaller/Nuitka coherence gate passed. Production remains
blocked on the installation, signing, security, legal, and clinical gates below.
Those six files are now superseded as final candidates because current source has
changed and requires a fresh build after the licensing-format decision.

## Workstation

- [ ] BLOCKED — Clinical behavior preserved — The owner accepted the source Developer Run, but none of the new installers has been executed on a clean workstation or clinically exercised.
- [ ] BLOCKED — Viewer features intact — Overlays, measurements, reference lines, sidebars, synchronization, and thumbnails were not all rechecked from an installed 3.6.5 package.
- [ ] BLOCKED — FAST mode safe — Packaging guards passed, but installed FAST-mode validation has not confirmed that no VTK render window is instantiated.
- [ ] BLOCKED — Metadata and DICOM handling preserved — Build coherence passed, but installed DICOM compatibility, stale-study isolation, overlays, and metadata behavior were not clinically verified.
- [ ] BLOCKED — Cardiac Flow interoperability — Automated VM-normalization guards and both-backend package inclusion pass, but a representative export has not been re-imported into cvi42 and flow quantification has not been confirmed.
- [ ] BLOCKED — Tests and log review planned/done — Forty-one focused build guards and cross-backend coherence passed; installed GUI checks and post-install `user_data/logs/` review remain outstanding.
- [ ] BLOCKED — Rollback plan exists — Prior installers were preserved, but a clean-machine upgrade/rollback rehearsal and data/config rollback procedure have not been recorded.
- [ ] BLOCKED — Performance change does not disable functionality — Nuitka Stage 6 uses `/Od` to avoid MSVC compiler heap failure; installed startup and runtime performance have not been measured.
- [ ] BLOCKED — Installer trust — Windows Authenticode reports `NotSigned` for all six installers; the documented code-signing gap must be closed before public distribution.
- [ ] BLOCKED — Third-party licensing — GPL codec removal and an installed notice are implemented, but the Qt commercial/LGPL basis and complete upstream license-text bundle require legal confirmation.
- [ ] BLOCKED — Offline license design — The current embedded shared-secret verifier can be extracted and used to forge licenses. Public-key verification requires owner approval because legacy installations must be reactivated.

## Cross-project

- [x] CONFIRMED — API/data boundary documented — The release record identifies the packaged mammography/EchoMind authorization boundary and links the relevant architecture documents; the build recovery did not add a new external API.
- [x] CONFIRMED — Data ownership documented — The release and subsystem documents retain the workstation/server and packaged-payload ownership boundaries; the build process did not migrate or write clinical data.
- [ ] BLOCKED — Privacy/PHI reviewed — No clinical data was copied into the build record, but the repository readiness audit still requires credential revocation/rotation, runtime secret loading, history cleanup, and secret-scanning guards before publication.
- [ ] BLOCKED — Manual approval point before production — The owner authorized local build generation only; production distribution approval has not been given.

## Blocking items

1. Install each intended edition on an isolated clean Windows machine and exercise the complete clinical/viewer acceptance checklist.
2. Validate upgrade and rollback using preserved prior installers and record configuration/database recovery steps.
3. Test the ARM64-emulated package on real Windows-on-ARM64 hardware; it is not a native ARM64 build.
4. Review installed logs for exceptions, thread/socket failures, stale caches, and DICOM or codec errors.
5. Complete the credential remediation and privacy review required by the repository readiness audit.
6. Sign the approved installers with the organization certificate, verify the resulting Authenticode chain and timestamp, then regenerate and recheck the manifests and SHA-256 lists because signing changes the files.
7. Obtain explicit owner approval after reviewing the installed-build evidence.
8. COMPLETED — Superseded the first 3.6.5 files with freshly compiled installers from the corrected latest source; verified Slicer/profile contents, 3.6.5 File/Product metadata, hashes, Qt/ICU hygiene, and cross-backend coherence.
9. BLOCKED — Build the next 3.6.5 candidate only after the owner chooses whether legacy licenses may be invalidated; current source differs from the last accepted build snapshot.
10. Confirm Qt licensing/compliance and preserve complete third-party license texts in the distribution.
11. Export an authorized de-identified cardiac Flow study and confirm cvi42 import and flow quantification.

## Sign-off

Manual approval given by: NOT YET GIVEN
