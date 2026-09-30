# AI-PACS 3.6.8 Client build record

Date: 2026-09-26
Status: COMPLETED; four Client installers independently verified
Role: Client only
Lane: receipt-backed canonical release candidate

## Frozen input and start evidence

- Published source commit: `050cb0b3f17acad274467ce3027797de081cf65d`.
- Annotated release tag: `v3.6.8`; verified on `main` and `beta-version`
  at all three configured remotes (`origin`, `p2`, `satar`).
- Git synchronization receipt: `generated-files/release-git/v3.6.8-050cb0b3f17a.json`.
- Immutable candidate workspace: `C:\b\aipacs-release-3.6.8-20260926-client-r1`.
- Canonical coordinator: `tools/build/build_local_candidate.py --target client`.
- PyInstaller backend started at `2026-09-26T14:32:03Z`; Nuitka ran sequentially afterward.
- Candidate manifest and `build_status.json` are the authoritative running evidence.
- Pre-build source, plugin-mirror and codec gates passed in the isolated candidate.
- Six authorized local configuration/profile files were preserved outside the
  candidate and restored byte-for-byte after capture, with SHA-256 verification.
  A subsequently generated runtime profile was separately preserved, not discarded.
- The temporary shared-source write freeze was released after capture. Later
  development edits are not part of this candidate and must not modify its source.

The frozen-input record establishes provenance. Completion evidence is recorded
below; installed QA, signing, distribution approval and clinical acceptance remain separate.

## Completed PyInstaller backend

The PyInstaller backend completed with exit code 0 at
`2026-09-26T15:02:53Z`; Nuitka then started from the same frozen candidate.
The following files are in the canonical `builder/output/installer/` folder.
Independent lengths, SHA-256 values and Windows FileVersion/ProductVersion
checks agree with `distributions-client.json`; both resource versions are 3.6.8.

| Edition | Bytes | SHA-256 |
|---|---:|---|
| Standard | 627,942,597 | `1639d526d4293c1f9f1e706a8aecaac74d71f3915b78d17ea2634157e0850f0e` |
| ARM64-emulated | 627,942,756 | `6efaa95a6d69cdc33f15af16ee233afe61a90027c67ff45c1fbaa54fcff61912` |

- Both compact editions are within the expected size range and 700,000,000-byte budget.
- Stage configuration parity passed for all 28 sanitized templates; all eight
  optional packages, five codec distributions and education payload parity passed.
- Frozen MPR geometry and Lite Viewer frozen-bundle self-test passed.
- Slicer startup, presentation, unified logging and numeric-control companion
  hashes independently match the frozen source, including `bin/Python/startup_script.py`.
- The frozen PYZ inventory contains cardiac Flow VM normalization, DICOMDIR,
  the native graphics probe and the Eagle Eye administration resolver.
- Inno compile times: Standard 684.329 seconds; ARM64-emulated 610.390 seconds.
- Inno warned about admin installation combined with per-user paths; installed
  lifecycle behavior still requires human QA. Optional PyInstaller hook warnings
  for `charset_normalizer.md__mypyc` and pycparser tables were recorded in the log.

## Completed Nuitka backend and final matrix

Nuitka completed with exit code 0 at `2026-09-26T16:28:43Z`.
The coordinator reports `completed`; cross-backend coherence exited 0 and confirmed
version 3.6.8 and the same eight optional packages. Final files below are in
`builder nuitka/output/installer/`, not the scratch/staging tree.

| Edition | Bytes | SHA-256 |
|---|---:|---|
| Standard | 610,468,940 | `e7fc02e46bbe593048b78dd993762f2ce1bbf63d9c345c6280aca229e3599f06` |
| ARM64-emulated | 610,469,168 | `72d4d70eb7ce4860ca0caa8fbade850c07408fe05db49b708d956cd3a48e7c24` |

All four final file lengths and SHA-256 values independently match their backend's
`distributions-client.json` and `SHA256-client.txt`. FileVersion and ProductVersion
are 3.6.8 for each installer. Metadata is `compiled`, `published: false`, role
`client`; both folders contain their generic and role-specific notes/checksums.
No version-3.6.8 `.partial` or `.tmp` installer remains. No Eagle Eye Server
installer was produced, uploaded or deployed.

### Final content checks

- Nuitka Stage 6 XML records compiled cardiac Flow VM normalization, DICOMDIR,
  native graphics probe and Eagle Eye administration modules. Its
  `included_metadata` entries explicitly cover all five required codec distributions.
- Independent Nuitka stage checks passed for 28 sanitized configuration templates,
  all eight optional packages and 37 mirrored education files.
- A diagnostic applying PyInstaller's physical dist-info-directory checker to
  Nuitka returned FAIL for missing directories. That is not a suitable Nuitka
  metadata gate: installed Nuitka 4.1.3 `ConstantCodes.py` embeds METADATA and
  `entry_points.txt`, and the compilation report confirms their inclusion.
  The [official metadata-loader implementation](https://nuitka.net/apidoc/MetaPathBasedLoaderImportlibMetadataDistribution_8c_source.html)
  documents this embedded representation. This diagnostic was not called a pass.
- Both staged cores contain exactly one Qt6Core DLL matching the build environment,
  no foreign ICU DLLs at the runtime search roots, and retain WebEngine `icudtl.dat`.
- In both backends, independently compared hashes match the frozen source for
  resident service, `AIPacsBackgroundRuntime.py`, startup, presentation, launcher,
  unified logging and numeric controls. The runtime's own startup entry point also matches.
- Both Lite Viewer frozen-bundle self-tests passed. Hidden Slicer warm-up and actual
  UI appearance still need installed human QA; file parity is not a live GUI pass.
- The final frozen source fingerprint still matches `build_source_manifest.json`.
  The existing edition validator independently passed against all four actual
  Standard/ARM stages: complete Slicer and resident/reference-only client
  integration, without Eagle Eye Brain or offline Lumbar model payloads.
- Post-build documentation checks passed `git diff --check` and eight canonical
  runbook tests using `.venv` pytest. `.venv_build` has no pytest installed;
  no build-environment dependency was added merely to run documentation tests.
- Required EULA/third-party-notice installer inputs are retained. Their presence
  does not grant legal redistribution approval or resolve historical credentials.

### Measured time and warnings

PyInstaller took approximately 30 minutes 50 seconds; Nuitka approximately
85 minutes 50 seconds. Total backend time was approximately 1 hour 56 minutes
40 seconds, excluding source preparation and independent final inspection.
Nuitka Stage 6 took approximately 53 minutes 59 seconds; Inno Standard took
839.093 seconds and ARM64-emulated took 740.563 seconds. This four-file Client
measurement is not a six-file or Server benchmark.

Nuitka logged the expected `/Ox` to `/Od` stability override, ignored duplicate
graphics data-file declarations and retained Windows runtime DLLs. Inno's
admin/per-user-path warning applies to both backends and remains an installed-QA
item. No stability flags were relaxed and no compiler or installer-compression
parallelism was increased. The verified native Slicer cache was reused, not rebuilt.

## Acceptance and publication boundary

The source tag/branches were synchronized before compilation. These post-build
documentation updates are local evidence, not a moved/reissued `v3.6.8` tag or
an assertion that the completed installers were uploaded. The immutable snapshot
and original Git receipt remain the installer provenance.

The coordinator's receipt-backed-lane `distribution_approved` field is not evidence
of regulatory/legal, credential, signing or clinical approval. The manifest and
status explicitly retain `production_accepted: false`; actual production approval
has not been given. Clean install/upgrade/uninstall/rollback, Windows-on-ARM64,
frozen Settings and Slicer UI/hidden warm-up, clinical workflows, de-identified
Flow re-import, log review, credential remediation, legal review, signing and owner
sign-off remain required before production distribution. Source GUI and known
repository-wide baseline failures remain documented in the release record.

## Requested output contract

- builder/output/installer/ai-pacs standard v3.6.8.exe
- builder/output/installer/ai-pacs arm64-emulated v3.6.8.exe
- builder nuitka/output/installer/ai-pacs standard v3.6.8.exe
- builder nuitka/output/installer/ai-pacs arm64-emulated v3.6.8.exe

Use RELEASE.md followed by BUILD.md and
tools/build/build_local_candidate.py --target client --git-sync-receipt.
No alternate build/output route and no Eagle Eye Server installer are authorized.
Reuse generated-files/distribution-assets-native-3.6.7-vc143-20260923 without
recompiling the verified native Slicer baseline. Stage current Python/UI overlays
from the immutable 3.6.8 snapshot; never substitute historical 3.6.7 installers.

## Verification coverage

The records above cover source SHA/tag/receipt, the isolated candidate, tests,
mirror/cache/native parity, toolchain, times, exit codes, coherence, independent
artifact lengths/hashes/version resources, Qt/ICU, codec, Flow, required legal
inputs, Lite Viewer, edition content and the remaining acceptance gates.

Compilation completion is not production acceptance. Acceptance status and
exclusions are in VERSION_3.6.8_RELEASE.md.

## Pending next candidate: vascular and bronchoscopy (2026-09-27)

Owner explicitly requires the latest Advanced Analysis changes in the next
applicable output. Follow the mandatory
[next-build inclusion checklist](../release-and-build/ADVANCED_ANALYSIS_NEXT_BUILD_2026-09-27.md)
from BUILD.md before candidate capture. This is later work, not part of the
completed September 26 installers or their recorded hashes.

For a candidate containing this work, the earlier instruction above to reuse the
September 23 asset cache is superseded by the requirement for a fresh immutable
cache containing VMTK, passed via --asset-root. The native Slicer executable is
still reused without recompilation; current Python/UI overlays and the separately
compiled compatible VMTK DLL/PYD bundle must both be packaged. Inclusion and
artifact acceptance remain pending until recorded against the new candidate.
