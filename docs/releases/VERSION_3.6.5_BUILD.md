# AI-PACS 3.6.5 build preparation

Updated: 2026-09-06

## Scope and status

The user requested new Python/PyInstaller and Nuitka builds at version 3.6.5.
The canonical project version and source application's displayed version were
updated. The owner accepted the latest Developer Run and authorized a local
candidate of all current source changes. The isolated matrix runner records actual
progress in `build_status.json`; preparation is not compilation success. No
installer has been published and no branch or tag has been pushed. The runner
creates local-only snapshot commits for provenance, not a release commit upstream.

The development checkout contains substantial pre-existing tracked and untracked
work across imaging, download management, DICOM handling, viewer stability,
offline lumbar analysis, and packaging. Preserve this checkout. The build-readiness
report requires a clean isolated source candidate; do not bypass that requirement
by treating the pre-build gate's dirty-tree warning as release approval.

## Candidate changes

- Mammography Intelligent AI Analyze is integrated with the native imaging UI and
  shares EchoMind's existing provider authorization boundary.
- Stale mammography CSV source paths can resolve through immutable viewer source
  hints on the worker thread. Ambiguous identities and foreign studies fail closed.
- Classification remains associated with the original CSV identity when the local
  DICOM filename differs. Model-facing metadata excludes raw source paths and IDs;
  burned-in identifiers in image pixels are not certified as removed.
- Existing MRI/spine and other workstation changes remain in the working tree.
  These are included under the owner's latest Developer Run acceptance.

## Verification performed during preparation

- Direct pytest: 36 passed, three third-party SWIG deprecation warnings, exit 0.
  Targets: EchoMind credential obfuscation, mammography intelligent analysis,
  Eagle Eye default build inclusion, distribution profiles, offline lumbar payload.
- Build-environment dependency check: no broken requirements, exit 0.
- Version consistency: project, source application, and shared builder all read
  3.6.5. Generated Windows version resources are intentionally left for the build
  to regenerate; old staged resources are not release evidence.
- Plugin mirrors: 462 matching pairs, zero plugin-only files, exit 0.
- Direct builder suite, offline test mode only: 102 passed, 7 failed, 5 deselected,
  exit 1. Six failures concern previously documented Nuitka ARM support; one
  concerns the old stage's `patient_table_sort.json`. These do not establish a new
  3.6.5 regression and were not hidden or quarantined.
- Online pre-build verification stalled in Git credential interaction. Its own
  process tree was stopped without touching the running workstation. The first
  builder-suite attempt hit the same fetch timeout. The subsequent suite used
  `AIPACS_SKIP_GIT_FETCH=1` for offline tests only, not as release approval or a
  build override. Remote source freshness remains unverified.
- No live GUI retry, clean-machine install, upgrade/rollback, or clinical acceptance
  was performed. Earlier test results are not substitutes for installer QA.

## Build contract

Python means the supported PyInstaller packaging chain, not a loose source ZIP.
Its default produces Eagle Eye, Standard, and ARM x64-emulation editions. The
independent Nuitka chain now uses the same three edition profiles and canonical
Inno scripts. The backend is identified by its existing installer folder, so the
versioned installer filenames are identical across the two folders. ARM means
`x64_on_arm64` emulation, not native ARM64.
Both must compile current sources, carry 3.6.5 metadata, pass their applicable
gates, and produce fresh artifacts with recorded sizes and SHA-256 hashes.
Do not use plain resume against older checkpoints or rename old installers.

No customer distribution is authorized by this local build request. Public
distribution additionally requires clinical and installer QA, privacy review,
rollback evidence, and owner review of historical credential exposure.

## Local candidate procedure (2026-09-04)

Use `tools/build/build_local_candidate.py` with the build interpreter, a new
workspace on a drive with sufficient free space, and the verified
`generated-files/distribution-assets` cache. `--prepare-only` creates a clean
local Git snapshot; `--run-prepared` starts both backends sequentially. Neither
command publishes or launches the workstation. Compilation remains isolated, but
the versioned release files and refreshed notes/checksums are written only to the
development repository's established `builder/output/installer/` and
`builder nuitka/output/installer/` folders. Existing differently named or older
versioned installers are not selected as current 3.6.5 artifacts.

The source manifest records original HEAD, current file hashes, candidate commit,
3.6.5, sanitized configuration, and the absence of production acceptance. No old
checkpoints, compiled outputs, clinical data, local environment files, or broad
generated-files tree is copied. Nuitka resume rejects changed source/version/
toolchain identities. The shared coherence check also compares each stage to
the current source version, not just to the other stage.

New fail-before guards cover generated-resource leakage, missing edition support,
automatic GUI launch, equally stale stage versions, and missing codec discovery
metadata in staged Nuitka. The 14 new guards pass. The combined builder and
credential suite has 127 passes and one failure against the existing 3.6.3 stage's
patient-table sort template before the final codec guard was added; that old stage
is not reused or altered. Historical pagination and Lite Viewer failures remain
known runtime risks; manual Developer acceptance does not establish their repair.
Remote GitHub freshness could not be confirmed without account interaction;
the accepted input is explicitly this local Developer source, not a claim about
unfetched remote commits. Clean-machine installation, upgrade, rollback, ARM-host
testing and clinical acceptance remain required before customer distribution.

## First local attempt — 2026-09-04 (failed; preserved)

- Workspace: `C:\AI-PACS-Builds\v3.6.5-20260904-01`.
- Source: `source/`, a local committed snapshot of the accepted working tree.
- Status: `build_status.json`; orchestrator logs: `runner.log` and `runner-error.log`.
- Per-backend logs: `python.log`, then `nuitka.log` when the queued backend starts.
- Snapshot verification: **127 passed, 2 skipped, 5 deselected**, direct pytest
  exit 0. The two skips require a staged executable that does not exist yet in
  the fresh workspace; they must not be interpreted as installed-build passes.
- The Python process started at 04:23:10 UTC. Asset verification and the normal
  pre-build gate passed. The log subsequently confirmed **PyInstaller 6.11.1 /
  Python 3.13.5 started a clean compilation**. Nuitka is queued by the same
  durable runner and is not yet claimed as started or completed.
- The source-freshness gate explicitly warns there is no upstream on this local
  snapshot; its PASS does not verify GitHub freshness. No gate bypass was used.
- Both backend output roots are fresh; existing Developer outputs were not
  overwritten. The generated Windows version resource is intentionally excluded
  from the source-input fingerprint and regenerated from version 3.6.5.
- Outcome: Python core compilation, frozen MPR verification and post-stage gates
  passed, but Inno stopped at an existing source file whose absolute path was
  261 characters. Nuitka then reported `MemoryError`, MSVC C1060 and C1002, and
  its process tree remained alive without progress. No final installers were
  produced. The owned build process tree was stopped for recovery; the Developer
  app, source snapshot, compiled Python core and logs were preserved.

## Guarded recovery — 2026-09-04

- A synthetic Inno probe reproduced failure at 261 characters (exit 2) and
  success with identical bytes at 37 characters (exit 0); neither generated
  installer was executed. `tools/build/probe_inno_path_limit.py` reproduces it.
- Real compiler input trees now use unique short paths under `<drive>:\ap-stage`
  or an explicitly configured `AIPACS_PACKAGING_STAGE_ROOT`. A 240-character
  guard runs before staging. Short stages are temporary compiler inputs only.
  Completed installers, `distributions.json`, install notes and checksum files
  are placed directly in each backend's existing `output/installer` folder.
- Nuitka full-core builds explicitly use one compile job, low-memory mode,
  disabled compiler cache and no LTO. This is slower but avoids the previous
  unbounded parallel compiler heaps. No application functionality is removed.
- Build subprocesses now fail immediately on fatal compiler memory messages,
  terminate only their owned process trees, and enforce execution/idle timeouts.
  The supervisor writes atomic statuses, records queued backends, catches child
  failures and requires a final cross-backend coherence pass.
- Recovery candidate workspace: `C:\b\365r3`. The earlier `C:\b\365r2` retry
  correctly terminated and recorded a Windows console encoding failure before
  compilation. UTF-8 subprocess I/O and a legacy-console-safe logging fallback
  now have a fail-before regression test; the failed retry is preserved.
  Python packaging may reuse only
  the earlier 3.6.5 core whose runtime/resource/spec inputs match the new snapshot
  exactly. `tools/build/repackage_candidate.py` verifies both recorded and actual
  source hashes, reruns pre/post-stage and frozen-MPR gates, and records the core
  executable SHA-256. A mismatch requires recompilation, not a bypass.
- Regression evidence: three targeted guards failed before correction; path,
  memory flags and fatal-exit guards pass afterward. Additional guards cover a
  silent-child timeout, stale source rejection and early path-budget failure.
  The isolated second candidate passed 133 tests with two unstaged-output skips
  and five deselections before the additional Unicode logging guard was added.
- The `C:\b\365r3` snapshot passed **134 tests, 2 skipped, 5 deselected**,
  direct exit 0. Its pre-build and retained-stage gates passed, as did the frozen
  MPR verification. Python packaging completed into the superseded candidate
  layout. The run was deliberately stopped before Nuitka completion when review
  found that final deliverables must use the repository's established installer
  folders. Its `build_status.json` records Python completed, Nuitka failed with
  the supervisor stop code, and no publication. Those artifacts are not the
  canonical 3.6.5 release set.
- The corrected installer-folder contract has a fail-before/pass-after guard:
  31 focused distribution and candidate-packaging tests pass with direct exit 0.
  A fresh candidate is required after this contract change; no earlier candidate
  output may be renamed or promoted.
- Rollback is to retain the failed attempt and stop the new owned build job;
  no production deployment or history rewrite is involved. Installer QA and
  clinical/ARM-hardware acceptance remain outstanding.

The memory policy follows the installed Nuitka CLI and the
[official memory troubleshooting guidance](https://nuitka.net/user-documentation/common-issue-solutions.html).

## Completed local build — 2026-09-05

### Corrected final candidate (latest accepted source snapshot)

Candidate `C:\b\365r12` completed both backends with coherence exit code 0.
It supersedes the earlier undersized 3.6.5 tables below. Standard and ARM now
retain the complete Advanced MPR/Slicer runtime and exclude only the Eagle Eye
offline-lumbar model. All six installer FileVersion and ProductVersion values
are `3.6.5`.

| Backend | Edition | Bytes | SHA-256 |
|---|---|---:|---|
| Python | Eagle Eye | 1,150,458,946 | `d788944bb07ee631141caf714dc264fe6f2e9c2e0c3786ab4bb1e0a94fe0831c` |
| Python | Standard | 629,116,007 | `1d7a77adc49d73ccf824f2129ff2efd14bce32e165a7982b56a16bddd3353338` |
| Python | ARM64 emulation | 629,116,119 | `3e7ac88ceff41e105982b9522ab3cbbb93fc4c8869560e8edc7471fed6e1400d` |
| Nuitka | Eagle Eye | 1,111,146,103 | `7d1feab2ac78fd0fad194b9e647de02fb6c9290dc673667f1f2025442f3e65ed` |
| Nuitka | Standard | 589,812,822 | `aafa20473e0507f1ff78c17ad7915bd1bb24d43e1e178faf2c1bf5b43c0ffaca` |
| Nuitka | ARM64 emulation | 589,812,885 | `5073b43a0e7ef38f87a382a28a2fd875af0aef6c328e3e1ed57104b74ac71aff` |

The PyInstaller and Nuitka stages contain zero app-local `icuuc.dll`,
`icuin.dll`, or versioned `icudt*.dll` files. Qt WebEngine's distinct
`icudtl.dat` remains present. The freshly rebuilt Lite Viewer removed the same
foreign ICU DLLs and its frozen `--selftest` passed on the warm-up run with all
four codec distributions. Asset-cache verification used bounded SHA-256 reads
after Windows returned `EINVAL` from `hashlib.file_digest()` during an earlier
Nuitka preflight; expected size and digest checks remained mandatory.

Nuitka stages 0 and 6 through 10 completed, including the full 1,637-unit MSVC
compile, link, resource/plugin staging, and all three Inno installers. The final
cross-backend check reports matching application version 3.6.5 and all eight
optional packages. No workstation executable or installer was launched.

The corrected recovery completed both backend pipelines without publishing or
launching the workstation. Final artifacts were written only to the repository's
established backend installer folders. Legacy installers already present in those
folders were preserved and are not part of the 3.6.5 manifests.

The PyInstaller/Python backend produced:

| Edition | File | Bytes | SHA-256 |
|---|---|---:|---|
| Eagle Eye | `builder/output/installer/ai-pacs eagle-eye v3.6.5.exe` | 1,167,531,876 | `e2891c2b1641f392502107097f0672894bb19631b81d1b2ea31fcc5f79c10c64` |
| Standard | `builder/output/installer/ai-pacs standard v3.6.5.exe` | 442,928,735 | `13b5372ebb184cf1dbfd6cdbe62f741d3ff90235d9764619abbdbf2cdb317edb` |
| ARM64 emulation | `builder/output/installer/ai-pacs arm64-emulated v3.6.5.exe` | 442,928,888 | `e4ef4bcf6a48ae990f086bcbe647c9899f1f3cb7cfd53c6289f1a1573c9f8c5f` |

The Nuitka backend produced:

| Edition | File | Bytes | SHA-256 |
|---|---|---:|---|
| Eagle Eye | `builder nuitka/output/installer/ai-pacs eagle-eye v3.6.5.exe` | 1,117,736,925 | `4e10b278d11bed880a181b4dfd90d199406917d34af15dacb17f76d8ddca9e37` |
| Standard | `builder nuitka/output/installer/ai-pacs standard v3.6.5.exe` | 393,142,029 | `b6c92e22cb8eabc2451bc46e60ae6074747a68e3af0d91fa61c03af7cfe93b95` |
| ARM64 emulation | `builder nuitka/output/installer/ai-pacs arm64-emulated v3.6.5.exe` | 393,142,163 | `72d24affdb3d2ce3922c93dafa697f08d56cace68ad5352e7ff7506e12b0b3e0` |

Each folder also contains its backend metadata, `distributions.json`, English
installation notes, and SHA-256 lists. Independent post-build calculation matched
all six recorded sizes and hashes; neither folder contains a `.partial` file.
Both compact installers remain below the 700,000,000-byte compact-edition budget.
Windows Authenticode inspection reports `NotSigned` for all six installers. This
is the repository's documented signing gap, not a hash mismatch; signing remains
required before treating the files as public production artifacts. Signing changes
the installer bytes, so the manifests and SHA-256 lists must be regenerated and
reverified after that step.

The first Nuitka Stage 6 recovery was terminated by the former 90-minute
no-output watchdog while MSVC was still working. The default idle boundary is now
four hours for this heavyweight compiler stage. A subsequent attempt reached a
real MSVC `C1002` pass-2 heap failure in the generated SimpleITK translation unit.
Stage 6 now appends `/Od` through the MSVC `_CL_` environment, overriding Nuitka's
`/Ox` for generated Stage 6 C units. This reliability tradeoff allowed the serial,
low-memory full-core build to complete; native third-party binaries remain their
precompiled artifacts. Resume selection now starts at the recorded failed release
stage instead of accidentally entering experimental stages. Exact Stage 6 timeout
recovery also preserves its object boundary while removing a partial distribution.

Nuitka stages 6 through 10 completed successfully. The bundled Lite Viewer build
completed, but its three frozen `--selftest` warm-up attempts timed out on this
host; the documented source self-test fallback passed Qt rendering, pydicom 2.4.5,
and the pylibjpeg OpenJPEG/RLE/libjpeg codec checks. This is build evidence, not a
clean-machine installed-viewer acceptance result. Inno emitted its existing
non-fatal warning that `PrivilegesRequired=admin` is combined with per-user data
areas; installer policy should be reviewed separately rather than silently changed
during this recovery.

Post-build verification passed:

- Cross-backend staged coherence: application version 3.6.5, eight matching
  optional packages, and the required Nuitka Stage 6 report.
- Focused distribution, candidate-packaging, and ARM parity suite: 41 passed,
  direct pytest exit 0.
- Synthetic compiler-only distribution verification: Standard, ARM64-emulated,
  and Eagle Eye profiles passed; a missing offline model was rejected.

The ARM artifact is an x64 build constrained for Windows-on-ARM64 emulation; it is
not a native ARM64 binary. No installer was executed. Clean-machine installation,
upgrade/rollback, real ARM64-host emulation, clinical workflow, privacy, and
production acceptance remain outstanding. `published` and production acceptance
therefore remain false.

## Post-build Standard/Slicer and version-display correction — 2026-09-05

The first completed 3.6.5 output set is superseded and must not be installed or
distributed. Its Python Standard installer was 442,928,735 bytes versus
628,247,370 bytes for 3.6.3 because the new edition profile physically removed the
entire 813,234,047-byte Advanced MPR/Slicer runtime. The size reduction was not a
compression improvement. The same defect affected the ARM64-emulated profile.
Eagle Eye retained Slicer and its offline lumbar model.

The corrected contract keeps and installs the standard Slicer runtime in Standard
and ARM64-emulated editions while removing only the Eagle Eye-specific
`offline_lumbar` environment, weights, and Slicer module. Advanced MPR remains
available in the package feed. Eagle Eye alone includes the offline lumbar model.
The Inno compiler receives separate `IncludeAdvancedMpr` and
`IncludeOfflineLumbar` definitions, so a missing model cannot disable the standard
Slicer payload and a compact edition cannot accidentally carry the model.

The application Information panel also contained two hardcoded 3.6.4 edition
lines and a 3.6.4 fallback even though the primary label read
`QApplication.applicationVersion()`. Those static values now follow the running
application version, the fallback is 3.6.5, and the old quarantined test has been
replaced with an active project-version parity guard. Inno already received
3.6.5 through `MyAppVersion` and stamped `AppVersion`, `AppVerName`, and
`VersionInfoVersion`; the Wizard title now explicitly displays
`AIPacs 3.6.5 Setup` through the same macro.

Fail-before evidence reproduced missing Slicer in Standard/ARM, the unsplit Inno
availability boundary, and the 3.6.4 Information fallback. The first five focused
guards pass after correction; the full Information/distribution selection passes
21 tests and the real Inno compile-only probe passes all three editions while
rejecting an Eagle Eye stage without its model manifest. New corrected installers
must be compiled from a fresh source snapshot; none of the earlier 3.6.5 files may
be renamed or promoted.

## Final-readiness revision — 2026-09-05

The six corrected installers listed above are now superseded as final candidates,
although retained as valid build evidence. Source changes made after the accepted
snapshot include the Eagle Eye brain additions and the DICOM codec/legal correction
recorded in `../reports/V3.6.5_FINAL_RELEASE_READINESS_2026-09-05.md`. A new build of
all three editions on both backends is required to represent the latest source.

The cardiac MRI Flow value-multiplicity correction is confirmed in both the old
snapshot and current source, and was present in both frozen backends. Its automated
guards pass. Actual cvi42 re-import and flow-quantification acceptance remains a
manual clinical interoperability gate.

The new build is intentionally not started until the owner decides whether the
legacy embedded-secret license format may be retired, because the secure offline
replacement invalidates existing keys and would otherwise force a second full build.

## Fresh local candidate r15 — 2026-09-06

Candidate `C:\b\365r15` is the latest complete local 3.6.5 build. It was made
from a fresh isolated snapshot after the Eagle Eye brain changes, DICOM codec and
legal corrections, and cardiac Flow VM-normalization work. Both backends returned
exit code 0 and the final cross-backend coherence check returned exit code 0.
`build_status.json` records `status: completed`, `published: false`, and
`production_accepted: false`.

An earlier r13 attempt failed closed after its temporary packaging tree inherited
the nearly full output drive. Edition staging has been corrected to exclude the
Eagle Eye-only offline model during Standard and ARM copy traversal, rather than
copying and deleting more than 2 GiB of model data. The local candidate runner now
places temporary packaging trees on the candidate workspace drive. A proposed r14
reuse was correctly rejected because the Eagle Eye brain source identity had
changed; r15 therefore performed a complete fresh PyInstaller and Nuitka compile.

| Backend | Edition | Bytes | SHA-256 |
|---|---|---:|---|
| Python | Eagle Eye | 1,156,051,065 | `ae78bf918eebe7e7c263e2978ca99f3c654b7c696b4958a16874ec1d5d2041e3` |
| Python | Standard | 634,708,026 | `e71274681e09a08ba305e4f518ad0a56867b275b7d38eebd5a638671c883b94c` |
| Python | ARM64 emulation | 634,708,231 | `d876d61b2f375132f042521e095726e48bd972b645d334a748f60947b7a97f86` |
| Nuitka | Eagle Eye | 1,117,929,527 | `0c9984d8f1bacc23e92f9c53e7decb6f54653b62e610e2d1329061f6a7be0cb9` |
| Nuitka | Standard | 596,594,493 | `7c3022ef5a7a5a7d29dd94396ab09542fe71f9a87157be69cf632f490dc9ee56` |
| Nuitka | ARM64 emulation | 596,594,689 | `ee3b1bf733877c14823e44e0216f6a27d2181cb8b9d3245fbc931a6da35a8ad8` |

Independent SHA-256 calculations matched both release metadata files and checksum
lists. All six installers report FileVersion and ProductVersion 3.6.5. The
PyInstaller staged application also reports 3.6.5 from its executable resource;
the common source sets `QApplication.applicationVersion()` to 3.6.5 and the active
Information-panel parity guard passes. Both Standard and ARM stages retain the
Advanced MPR/Slicer executable and exclude the offline lumbar model. Eagle Eye
retains both Slicer and the declared offline model. The ARM edition remains an x64
binary intended for Windows-on-ARM64 emulation, not a native ARM64 build.

The PyInstaller table of contents and the Nuitka compilation report both contain
`PacsClient.utils.dicom_vm_normalization` and `modules.dicom_media.dicomdir`.
The Nuitka report also records pylibjpeg, RLE, OpenJPEG, JPEG-LS, and GDCM codec
metadata. The final focused packaging, legal, Qt/ICU, Lite Viewer, Information,
DICOM VM-normalization, and ARM-parity suite passed 111 tests with direct pytest
exit code 0. The build environment passes `pip check`. Both staged cores have one
QtCore payload, no app-local foreign ICU DLLs, and the required WebEngine
`icudtl.dat`; the fresh Lite Viewer self-test passed during each backend build.

The installers include the established English and Persian installation notes,
SHA-256 lists, backend release metadata, EULA, and third-party notices. No partial
or temporary installer remains. The earlier r12 Nuitka set was moved intact to
`builder nuitka/output/installer/_superseded/2026-09-05-r12`; legacy releases were
not deleted.

This is a local candidate, not a production release. All six files are currently
unsigned. Clean Windows installation, upgrade/uninstall/rollback, real ARM64-host
emulation, installed-workflow/log review, representative de-identified cvi42 Flow
re-import and quantification, credential remediation, legal confirmation, and
explicit owner acceptance remain required before distribution. Inno's known
non-fatal `PrivilegesRequired=admin` versus per-user data-area warning also needs
clean-install policy validation. Signing will change the bytes and therefore
requires regenerated metadata and checksum files.

## References

- `builder/docs/DISTRIBUTION_EDITIONS_AND_OFFLINE_ASSETS.md`
- `builder/docs/AI_AGENT_BUILD_RUNBOOK.md`
- `builder nuitka/README_NUITKA_BUILD.md`
- `docs/reports/BUILD_READINESS_PYINSTALLER_NUITKA_2026-08-30.md`
- `docs/plans/EAGLE_EYE_MAMMOGRAPHY_INTELLIGENT_ANALYSIS_MERGE_2026-09-02.md`
