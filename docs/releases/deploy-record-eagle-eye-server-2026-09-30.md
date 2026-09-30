# Deployment Safety Record — Eagle Eye Server on Razi — 2026-09-30

**Change:** Replace the running Razi Eagle Eye Server PyInstaller 3.6.9 trial with the newer EchoMind local install-QA installer, without changing the version number.
**Candidate:** `builder/output/installer/ai-pacs eagle-eye v3.6.9.exe`, 2,789,415,074 bytes, SHA-256 `0dde830d3b130a2e27edcc38a38d8e0b2d975459e44119a724ce3687a2652d97`.
**Gate result:** BLOCKED for clinical/official qualification. The owner explicitly approved a Razi installation trial despite the stated test, privacy, and rollback gaps; that trial completed below. This is not a production-safety pass.

## Target and artifact evidence

- [x] CONFIRMED — Target identity — Read-only SSH returned `WIN-CTBQPS2GSM3` for the Razi `pacs` host.
- [x] CONFIRMED — Current service — `AIPacsEagleEye` is Running from `D:\Eagle Eye Server\installed\3.6.9\AIPacs.exe`; port 8002 is listening after installation and a bounded restart. The new `remote_backend.py` hash below identifies the newer candidate despite the unchanged version number.
- [x] CONFIRMED — Prior backup presence — `D:\Eagle Eye Server\backups\installed-3.6.9-20260928` exists. Presence does not establish successful restoration.
- [x] CONFIRMED — Candidate identity — Local and transferred SHA-256 and byte count match `docs/releases/VERSION_3.6.9_RELEASE.md` and the role-specific build inventory.

## Workstation and clinical checks

- [ ] BLOCKED — Clinical behavior preserved — No installed-host GUI, patient-workflow, or model-inference acceptance exists for this exact newer binary. Use de-identified/synthetic acceptance on an isolated host first, then a controlled target verification.
- [ ] BLOCKED — Viewer features intact — Overlays, measurements, reference lines, sidebars, sync, and thumbnails have not been checked in the installed candidate. Run affected GUI checks on the installed build.
- [–] N/A — FAST mode safety — The EchoMind transport change does not change FAST rendering or VTK construction; this does not waive general installed-viewer acceptance.
- [ ] BLOCKED — Metadata and DICOM handling preserved — No installed workflow check has ruled out regressions in patient/study identity and DICOM presentation for this repackaged candidate.
- [ ] BLOCKED — Tests and log review — Packaging checks and 23 focused EchoMind tests passed, but the broader EchoMind suite reported 14 failures. Installer completion, service startup/restart, and authenticated capability transport passed; installed GUI, model inference, clinical workflow, and application-log acceptance remain unverified. Resolve or explicitly triage each failure and complete installed acceptance.
- [ ] BLOCKED — Rollback — A new restricted backup of the exact previous installation, module packages, configuration, service definition, and uninstall registration was verified before cutover; the prior installer remains intact. Restoration has not been exercised. Same-version Inno upgrade removed the old installed files before replacing them. Prove recovery on an isolated host before treating this as production-qualified.
- [–] N/A — Performance optimization preserving functionality — This change is not a performance optimization.

## Cross-project and operational checks

- [x] CONFIRMED — API boundary described — `docs/echomind/RAZI_SERVER_PILOT_2026-09-27.md` describes the text-only authenticated client-to-PACS route and its exclusions.
- [x] CONFIRMED — Data ownership described — The pilot document assigns report processing to the PACS server and local workstation routing to the client; the updated server-source-only Web Search route is not deployed on the PACS endpoint.
- [ ] BLOCKED — Privacy/PHI review — The pilot documents direct public-IP HTTP and no HTTPS claim. Pilot authorization is not a clinical privacy acceptance for this installer; review data and credential exposure before using real patient content. Historical embedded-credential remediation also remains open in the release record.
- [x] CONFIRMED — Informed trial cutover approval — After being told that multiple EchoMind files changed, 14 tests failed, and rollback was untested, the owner explicitly authorized stopping and replacing the active Razi Eagle Eye service in this turn. This approval does not certify clinical safety.
- [ ] BLOCKED — Target functionality — The newer Web Search workflow requires an updated, separately deployed PACS server source; the currently installed central endpoint does not support it. Do not claim complete EchoMind functionality from this workstation installer alone.

## Owner-authorized installation trial

- Transferred the candidate to `D:\Eagle Eye Server\incoming\eagle-eye-3.6.9-echomind-20260929.exe`. Remote SHA-256 was `0dde830d3b130a2e27edcc38a38d8e0b2d975459e44119a724ce3687a2652d97`, and size was 2,789,415,074 bytes. The prior installer remains at `D:\Eagle Eye Server\incoming\eagle-eye-3.6.9.exe`, SHA-256 `9a9ea026189ecbb21e24cac798536f6edf8c29f832b514e9a0d8318efb846a23`.
- Captured the previous installation, ProgramData module packages, both configuration roots, SCM definition, and uninstall registration under `D:\Eagle Eye Server\backups\installed-3.6.9-before-echomind-20260930`. The backup root grants access only to Administrators and SYSTEM. Read-only Robocopy comparisons returned zero differences before cutover; the backed-up and then-current `AIPacs.exe` hashes matched. Existing `User Data` was not copied or modified by this backup.
- No queued or running Eagle Eye jobs were found immediately before stopping only `AIPacsEagleEye`. PACS local health was HTTP 200 and `ReceptionCrmServer` was Running. The Eagle Eye service and port 8002 stopped cleanly.
- Ran the transferred Inno installer under a one-time SYSTEM task with the existing `D:\Eagle Eye Server\installed\3.6.9` target. The installer log is `D:\Eagle Eye Server\logs\install-3.6.9-echomind-20260930.log`; it records `Installation process succeeded`, `User chose OK`, and `Need to restart Windows? No`. The task exit code was 0.
- The known unconditional Advanced MPR information `MsgBox` still blocked `/VERYSILENT` completion. After identifying the exact installer child process and expected dialog text, a one-time SYSTEM helper clicked only its OK button. The install and helper tasks exited 0 and were removed; the temporary helper script was removed. The installer source defect remains to be fixed before another unattended build.
- Installed profile reports version `3.6.9` and edition `eagle-eye`. The installed EchoMind `remote_backend.py` SHA-256 is `629f95d7b018a05496c06e8c9c7d9359faf79ff86fd708005e3438fd02c0f0a1`, matching the current payload mirror. The custom Slicer executable SHA-256 remains `e28c88dbda85fb919eac3b668e28f4f2f83c841c338338d700ba41c4cca814a0`. Breast and Bone Age each have an installed standalone runtime, runner, and manifest; this is payload presence, not model-inference acceptance.
- Started and then restarted `AIPacsEagleEye` successfully. Its port 8002 listener returned, an authenticated client capability request succeeded before and after restart (seven modules, four correction modules), PACS local health remained HTTP 200, and `ReceptionCrmServer` remained Running. The listener process resolves to the newly installed `AIPacs.exe`, whose hash differs from the backed-up previous executable. No recent AIPacs/Eagle Eye Application Error event was found in the bounded post-install window. No patient image, report, or inference job was used as a test.

## Unresolved qualification items

1. Triage the 14 EchoMind test failures and run the installed candidate's GUI, Session 0 service, logs, and synthetic clinical-workflow checks on an isolated Windows host.
2. Exercise restoration of the backed-up previous Razi service and configuration on an isolated host, then repair the installer lifecycle and unconditional information dialog.
3. Complete the PHI/transport and credential review; deploy or disable the server-only Web Search route before claiming it works.
4. Complete installed clinical and security acceptance before representing this owner-authorized trial as a safe production release.

## Sign-off

Manual trial cutover approval given by: project owner in chat after explicit risk disclosure. No production safety or official-release approval is claimed.
