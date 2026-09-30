# AI-PACS v3.6.9 release preparation

Release date: pending
Release commit: pending reviewed immutable SHA
Release tag: pending `v3.6.9`
Source branch: `beta-version`
Source publication status: BLOCKED
Production approval: NOT YET GIVEN

This record is preparation, not a release claim. Change publication status to
`READY` only after the complete source scope, verification, exclusions, security
findings, rollback and approvals have been reviewed. Never copy historical
v3.6.8 artifact evidence into this candidate.

## 2026-09-29 EchoMind Server PyInstaller install-QA rebuild (current Server Python file)

The owner requested only the Eagle Eye Server PyInstaller installer with the
latest EchoMind source, retaining version 3.6.9. No Nuitka build, Client build,
Git publication, or installation on a clinical host was requested. The
canonical `BUILD.md` single-backend local install-QA route used the immutable
snapshot at `C:\b\aipacs-internal-3.6.9-20260929-echomind-server-python`.
Its source fingerprint is
`51432b54fda80bf05645486cd331405de755d032a700d0baa68f94947ddb3ddf`,
with 7,667 recorded source inputs, `build_target=server`, and
`build_backends=[python]`. The coordinator completed with exit code 0 and
archived the prior Server PyInstaller binary and Server-specific metadata under
`builder/output/installer/_superseded/local-qa-3.6.9-20260929-213845-python`.
Cross-backend coherence is not applicable to this single-backend QA build.

| Backend | Current installer | Bytes | SHA-256 | Windows FileVersion |
| --- | --- | ---: | --- | --- |
| PyInstaller | `builder/output/installer/ai-pacs eagle-eye v3.6.9.exe` | 2,789,415,074 | `0dde830d3b130a2e27edcc38a38d8e0b2d975459e44119a724ce3687a2652d97` | 3.6.9 |

The independent SHA-256 and byte count match the new role-specific
`builder/output/installer/distributions-server.json`. The packaged EchoMind
`remote_backend.py`, `llm_client.py`, and changed viewer-chat files in the
PyInstaller stage match the frozen plugin-source copies byte-for-byte. The
snapshot also contains the new EchoMind transport in the source and mirror,
and both standalone Breast and Bone Age payloads have staged manifests,
runners, and bundled Python executables. The PyInstaller pre-build and
post-stage gates passed; the latter verified frozen runtime, sanitized config,
eight plugin packages, codec metadata, and Education parity. The architecture
scan reported the existing x86 `speech_recognition/flac-win32.exe` helper as
a non-blocking warning in the x64 stage.

The shared distribution cache verified 34,469 files / 4,356,143,152 bytes;
`pip check` passed; 46 packaging regression tests and 23 focused tests for
the new EchoMind remote backend/consultation path passed. The broader EchoMind
suite had 2,433 passed, 14 failed, 12 skipped, 4 expected failures, and 15
deselected: the failures include legacy prompt harnesses that select the new
remote route from this workstation's active center setting, plus an older
Turbo source-structure assertion. These are not counted as a full EchoMind
acceptance pass. No installed-host or service Session 0 acceptance was run.

The Nuitka Server installer remains the earlier QA file: 2,772,357,085 bytes,
SHA-256 `8e1cdf8bcc7d82de2e550a7d946ef94f5935a278479b997437b2f575a40927b7`.
All four current Client installer byte counts remained unchanged. The two
Server backends therefore do **not** share this EchoMind source snapshot.
This is local install-QA only; credential remediation, installed GUI/service
tests, model and redistribution review, signing, and exact Git synchronization
remain pending before production approval.

## 2026-09-29 Education/Thumbnail Client install-QA rebuild (current Client files)

The owner requested four updated Client installers under the existing 3.6.9
version, without rebuilding Eagle Eye Server. The canonical `BUILD.md` local
install-QA Client route created one isolated source snapshot at
`C:\b\aipacs-internal-3.6.9-20260929-education-client`, with source fingerprint
`139fea29986078eb6a517d4ff5b15eccc614db965d0a41c7a6cdd034b38adb46`
and 7,666 recorded input files. Both backends completed with exit code 0;
cross-backend staged coherence exited 0. Earlier same-version Client binaries
and their metadata were moved by the coordinator to `_superseded` within each
canonical installer folder. The Server installers were not selected or rebuilt;
independent hashes matched both previously recorded Server SHA-256 values.

Pre-build direct checks: 277 focused Education/Thumbnail/builder tests passed,
one existing quarantined test xfailed; 495 source/plugin mirror pairs matched;
the complete distribution cache verified 34,469 files / 4,356,143,152 bytes;
the build environment passed `pip check`. The snapshot includes the new
Education authoring/transfer/DICOM files and the current patient-thumbnail
modules. PyInstaller's staged Education files match its snapshot byte-for-byte
and its PYZ contains the patient-thumbnail module. Nuitka's compilation report
contains the corresponding Education and thumbnail modules. Both staged
Advanced Viewer payloads contain the custom executable, resident/vascular/
bronchoscopy modules, and the VMTK manifest. The Education and patient-tab
Python file lists and the 145 recorded file hashes still matched the live
checkout after the build. These are content checks, not installed GUI acceptance.

Each current Client installer below has Windows FileVersion 3.6.9, and an
independent SHA-256/size check matched its role-specific
`distributions-client.json` inventory:

| Backend | Edition | Canonical installer | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| PyInstaller | Standard | `builder/output/installer/ai-pacs standard v3.6.9.exe` | 629,077,642 | `3708ff38ad3deccb86a2b344f25abde2e263a36fc512558016d1669976c6d403` |
| PyInstaller | ARM64-emulated | `builder/output/installer/ai-pacs arm64-emulated v3.6.9.exe` | 629,077,695 | `c7d7d126bda14a881bf04f44b42fff698b8658153296d12b8455feab254672a0` |
| Nuitka | Standard | `builder nuitka/output/installer/ai-pacs standard v3.6.9.exe` | 612,548,841 | `b1bc2a518e5b69daad48237ef2a0dd2074a4ac020472a1485a1f633d195caf0e` |
| Nuitka | ARM64-emulated | `builder nuitka/output/installer/ai-pacs arm64-emulated v3.6.9.exe` | 612,549,045 | `2664533e327e8e18da0b441513f8840176ebf739003bdbd13f235cd5f43f89b8` |

This is a local install-QA candidate, not a publication or production-approved
release. Source GUI acceptance of the affected Education/Thumbnail workflow,
clean-host install/upgrade/rollback, ARM64-emulation acceptance, security/
redistribution/signing review, and exact three-remote Git synchronization
remain pending. The previous Server artifacts remain separate historical QA
outputs and must not be described as containing this later Client snapshot.

## 2026-09-29 earlier local install-QA rebuild (superseded Client files)

The user requested the latest `fix 1` thumbnail-card change and the Slicer
import repair in installable files for another PC. The canonical 3.6.9
installers were rebuilt through `BUILD.md`'s role-selected local install-QA
route. This supersedes the earlier same-version QA binaries and their hashes
below; it is **not** a release, publication, or installed-host acceptance.

The frozen Client candidate is
`C:\b\aipacs-internal-3.6.9-20260928-193238` (source fingerprint
`23ca0465dbcd92c774067ec33eda831d426b9bbc702d6d6f6afc9fba20d29cce`).
The separately frozen Server candidate is
`C:\b\aipacs-internal-3.6.9-20260928-212516` (source fingerprint
`2067a87cb6d99fcb9130623d45f1c593744cd7452a5d8654a7f0143b9f9e8626`).
Both coordinators and all four backend builds exited 0, and both staged
cross-backend coherence checks passed. These are different source snapshots:
the `fix 1` and Slicer files match between them, while a subsequent Home
search change is Server-only and a later Education change is in neither.
Do not describe all six as one exact-source release or as containing later
concurrent work.

Direct pre-build checks passed: 187 affected/adjacent thumbnail and UI tests,
44 MPR/Slicer tests, 90 builder tests, 486 plugin mirror pairs, and the full
34,469-file distribution-asset cache verification. `fix 1` source files match
between the two snapshots; the thumbnail module is present in both PyInstaller
PYZ tables and both Nuitka compile reports. The three checked Slicer resident
and lumen files match each candidate's source in all four backend stages.
Server PyInstaller and Nuitka stages contain the standalone Breast and Bone Age
manifests and Python runtimes. These are package-content checks, not a clinical
or installed Slicer GUI pass.

Each row below was independently compared with its role-specific
`distributions-client.json` or `distributions-server.json` at the time of that
earlier build; the file size, SHA-256, and Windows FileVersion 3.6.9 matched.
The four Client rows are archived superseded files. The earlier Server
PyInstaller row is also archived by the EchoMind rebuild above; the Nuitka
Server row remains in its canonical path. Paths are relative to the repository
root.

| Backend | Role | Earlier installer / remaining Nuitka Server installer | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| PyInstaller | Client Standard | `builder/output/installer/_superseded/local-qa-3.6.9-20260929-164126-python/ai-pacs standard v3.6.9.exe` | 628,947,247 | `24ef841de1c5bc40f099b28d9df23f9b19c66c2963e4b0a6cb3eada821dbd785` |
| PyInstaller | Client ARM64-emulated | `builder/output/installer/_superseded/local-qa-3.6.9-20260929-164126-python/ai-pacs arm64-emulated v3.6.9.exe` | 628,947,393 | `ecb79025b061d9176d8907236f571b457fc90799d9943e6788c1febf474ac10b` |
| Nuitka | Client Standard | `builder nuitka/output/installer/_superseded/local-qa-3.6.9-20260929-171358-nuitka/ai-pacs standard v3.6.9.exe` | 612,037,264 | `57490d1c739a0bd289882821d5c4cb48b1a8d974592e1215e3c3d3f2b7c0635d` |
| Nuitka | Client ARM64-emulated | `builder nuitka/output/installer/_superseded/local-qa-3.6.9-20260929-171358-nuitka/ai-pacs arm64-emulated v3.6.9.exe` | 612,037,406 | `91272c8eee6ee1add363ceb01219eb6d2e2fe1bfbc1f94b4d6ec65dd5b7783ba` |
| PyInstaller | Eagle Eye Server | `builder/output/installer/_superseded/local-qa-3.6.9-20260929-213845-python/ai-pacs eagle-eye v3.6.9.exe` | 2,789,284,765 | `e0e127dc1617eb289420a6f1baabdd66e084e2e41473bcbda47e22238c4b5119` |
| Nuitka | Eagle Eye Server | `builder nuitka/output/installer/ai-pacs eagle-eye v3.6.9.exe` | 2,772,357,085 | `8e1cdf8bcc7d82de2e550a7d946ef94f5935a278479b997437b2f575a40927b7` |

The Client PyInstaller role-specific metadata was restored by the coordinator's
same-candidate compiled-stage recovery after the Server build had displaced
it. Both Client installers were re-hashed against that completed compiler
stage; no installer file was manually replaced. The generic metadata in each
shared installer folder describes its last refreshed role, so select the
role-specific inventory and notes when transferring files.

Still pending: affected-workflow source GUI and clean-host installed tests,
ARM64-emulation host acceptance, Server service/upgrade/rollback and model
qualification, exact reviewed Git commit and multi-remote synchronization,
historical credential remediation, redistribution approval, and signing.
These QA files must not be represented as production-approved installers.

## Outcome and scope

Requested: four Standard/ARM64-emulated Client and two Eagle Eye Server
installers across PyInstaller and Nuitka. Current source includes later MPR,
Advanced Analysis/VMTK, Eagle Eye, EchoMind and stability changes. The exact
reviewed source inclusion list and GUI acceptance are pending.

The earlier, superseded non-promotable Client QA snapshot had source fingerprint
`1929720a9045a0e0fff1e2cdf0ecb62d79270b27ab395f5ae1f0a9d4e52d0f7a`.
The earlier, superseded Server QA snapshot had source fingerprint
`8cec0c0fcd1415be138d7cbd8abc04934aab2539316b671deed427b5e75382ca`.
These are not a common published release commit; the final release requires one
reviewed, synchronized Git identity and fresh matching outputs.

## Compatibility, migration, and stored data

Preserve the existing Client/Server role boundary and the shared VC143 Slicer
native baseline. No production service, model, credential, configuration or
DICOM migration is authorized by this preparation record.

## Verification evidence

| Gate | Evidence | Result |
|---|---|---|
| Version authorities | `pyproject.toml`, `main.py`, Information fallback, legal applicability lines | Prepared for 3.6.9; all six local-QA installers report Windows FileVersion/ProductVersion 3.6.9 |
| Build inputs | New VMTK/service cache: 34,469 inventory hashes, Slicer parity and pywin32 preflight | Passed independently, exit 0 |
| Focused tests | Direct pre-build selection and combined MPR selection | 150 and 39 passed, exit 0; frozen QA pending |
| Portable Server model inputs | Sealed Breast and Bone Age interpreters and manifests | 18,796 and 12,667 files respectively verified; synthetic jobs ran outside the source working directory; installed Session 0 acceptance pending |
| Build recovery | Nuitka Client VMTK asset-path and cross-role installer cleanup regressions | Preserved Stage 6/7 compilation resumed at Stage 8; both Nuitka Client installers and cross-backend coherence completed. Cross-role cleanup and bounded recovery guards pass; 94 focused packaging/engine tests pass overall. |
| Plugin mirrors | `verify_plugin_mirrors.py` | 486 pairs match, exit 0 before version preparation |
| Developer Run | User states the development mode was tested | General source acceptance; affected frozen workflows pending |
| Git synchronization | Exact three-remote receipt | PENDING |
| Earlier installer matrix (superseded Client and Server Python files) | Six exact paths, hashes and version resources | The earlier six local-QA installers were present in canonical backend folders, and both role/backend build coordinators completed with exit 0 and cross-backend coherence passed. Their earlier SHA-256 and size checks matched their then-current role-specific inventories. Use the Education/Thumbnail table above for current Client files and the EchoMind Server table above for the current Server Python file; only the earlier Server Nuitka row remains current. |
| Earlier observed size (superseded) | Earlier canonical installer files | Client PyInstaller: 628,941,676 and 628,941,846 bytes; Client Nuitka: 612,059,500 and 612,059,689 bytes; Eagle Eye PyInstaller: 2,789,279,701 bytes; Eagle Eye Nuitka: 2,772,313,621 bytes. These are historical local-QA measurements, not expected-size guarantees for current or signed files. |
| Clean install / upgrade / rollback | Isolated Windows evidence | PENDING |

## Deliberate exclusions

Local configuration, certificates, tokens, patient data, logs, generated
probes and completed build outputs must not enter Git or installer source.

## Known risks and blockers

Server portable Breast/Bone build inputs are prepared, but Breast still has an
explicit classification limitation. Model distribution/acceptance evidence, safe transactional
SCM installation and rollback, and both-backend clean-host verification. The
latest shared source is dirty and not yet reviewed or synchronized. Historical
credential incident response and clinical/privacy/signing approval remain
separate distribution gates. See the deployment safety record.

## Rollback

Keep v3.6.8 installer artifacts and its Git tag immutable. A failed local
candidate may be archived only through the documented role-selected build
recovery route. Once a release is published, correct it with a reviewed new
commit/version rather than moving a shared tag or force-pushing.

## Approval

Source publication approved by: NOT YET GIVEN
Installer distribution approved by: NOT YET GIVEN
