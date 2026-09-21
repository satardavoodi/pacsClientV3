# AI-PACS 3.6.6 build record

Status: LOCAL INSTALL-QA SIX-INSTALLER MATRIX COMPLETED; NOT PUBLISHED
Date: 2026-09-10

## Requested matrix

The repository owner requested a new version 3.6.6 build containing the latest
accepted Developer Run changes. The local install-QA lane completed all six
installers from one isolated source snapshot:

- PyInstaller: Eagle Eye, Standard, ARM64-emulated.
- Nuitka: Eagle Eye, Standard, ARM64-emulated.

Final files belong only in `builder/output/installer` and
`builder nuitka/output/installer`. ARM64-emulated is x64-on-ARM64 and is not a
native ARM64 build.

## Source and preflight evidence

- Source commit: `f8a68ed4f6da872fcf85d84f664ccf2cf09f86f2` on `beta-version`.
- Isolated snapshot fingerprint: `ce86d9f14862d701a26e83b271784e4c6a0e9792c61e958a7cc4d1bfa9738916`.
- Exact release synchronization receipt: not used by the local install-QA lane.
- Version authorities: 3.6.6.
- Mandatory build and printing selection: 216 passed, 6 third-party SWIG
  warnings, exit 0.
- Plugin mirrors: 462 pairs match.
- Runtime and build dependency checks: pass.
- Toolchain: Python 3.13.5, PyInstaller 6.11.1, Nuitka 4.1.3, Inno Setup 6.
- Distribution assets: 34,529 files / 4,329,814,502 bytes verified.
- Candidate-drive free space: more than the required 60 GiB.

## Artifact evidence

The completed local install-QA matrix was produced in the established repository
folders on 2026-09-10. All six files were independently re-hashed after the build;
every digest matched its backend `distributions.json`. Windows FileVersion and
ProductVersion are `3.6.6` for every installer.

| Backend | Edition | Bytes | SHA-256 |
|---|---|---:|---|
| PyInstaller | Eagle Eye | 1,784,777,452 | `4B5E6D797140CD4DDE8B5F8DFE359C9E3E303BE27F20EAF470821E64F2724EB7` |
| PyInstaller | Standard | 634,726,180 | `1F86D156452851F2E85FC8FC55DA14451AAA47FE87B8A608A16847E02E2E392A` |
| PyInstaller | ARM64-emulated | 634,726,240 | `24462047C805F1459EE8E3C3EC052822AF2B871A681DBDA7CB0A784C8E6135A7` |
| Nuitka | Eagle Eye | 1,744,964,718 | `5ABA2F405CA9DC4EE1949540C47E341AC4D8BFC5AE735DD06E5A408378B5A7CF` |
| Nuitka | Standard | 594,922,045 | `A611BED9BA6409EC20AB357A2D39E8CEC4728169E480B9EE87EE4D60141C48FA` |
| Nuitka | ARM64-emulated | 594,922,091 | `8ECCD8448FB7D4F25C1C986D3569A9E5BFAF454E62D6430CEE4144E90801FAA2` |

Post-build evidence:

- PyInstaller/Nuitka staged-output coherence: passed for version 3.6.6 and all
  eight optional packages.
- Focused packaging, edition, Brain/Lumbar, module installation, and Information
  version guards: 89 passed, 6 third-party SWIG warnings, exit 0.
- Lite Viewer 1.5.0 was rebuilt with the current Python 3.13.5 environment; its
  frozen-bundle self-test passed and all required DICOM codecs were present.
- Standard and ARM64-emulated installers are below the 700,000,000-byte compact
  installer limit for both backends.
- Eagle Eye staging contains Advanced MPR/Slicer, offline Lumbar weights, and the
  validated Brain/SynthSeg payload. Compile-only TensorFlow headers were excluded.

## Build-time measurement and reuse conclusion

The successful candidate workspace recorded about 49 minutes for exact-input
PyInstaller repackaging and about 3 hours 15 minutes for Nuitka. Nuitka Stage 6
took about 54 minutes. Its three Inno Setup compiles took 1,934.390, 876.625, and
771.484 seconds respectively, or about 60 minutes in aggregate; Stage 10 including
staging and verification took about 63 minutes.

Both backends already compile one application core and derive all three editions
from that core. The repeated cost is therefore not six full Python/native builds;
it is the required edition staging and compression of six standalone installers.
The current safe accelerators are the immutable asset cache, source-only validation
during development, explicit single-edition diagnostics, fail-closed PyInstaller
core reuse for exact inputs, and same-candidate Nuitka checkpoint recovery. A new
version or changed core input still requires a fresh final matrix. Cross-candidate
Nuitka core reuse and faster diagnostic compression remain guarded experiments,
not release defaults.

The recovery issue observed during this run is now covered by the canonical
coordinator's `--resume-workspace` path. A resumed full candidate skips a backend
already recorded complete, limits Nuitka recovery to release stages, and reruns
coherence instead of requiring an operator to improvise backend commands.
A real recovery exercise against the completed 3.6.6 workspace skipped both
completed backends and passed cross-backend coherence without compilation or
installer compression.

The first synchronized candidate was created at
`C:\b\aipacs-3.6.6-20260909-195559`. Its PyInstaller core, Qt/ICU hygiene, frozen
MPR geometry gate, version stamp, and Lite Viewer build/self-test passed. Packaging
then stopped before installer compilation because the local Eagle Eye Brain payload
did not contain `distribution-approval.json`; Nuitka was correctly skipped. The
failed candidate remains diagnostic evidence and is not promotable.

The 2026-09-10 coordinator correction moves this check before snapshotting or core
compilation and provides a one-command internal Standard PyInstaller path. This is
post-tag build-tool work and is not part of immutable tag `v3.6.6`; it must not be
used to move or silently replace that tag. No 3.6.5 installer may be renamed,
copied, resumed, or promoted as 3.6.6.

The first real one-command internal run reached a successful core build, Qt/ICU
hygiene, MPR bytecode verification, version stamp, and Lite Viewer self-test. It
then exposed a stale post-stage assumption that every edition required offline
Lumbar even after Standard correctly omitted Eagle Eye assets. The gate is now
edition-aware; the stopped internal workspace remains failed diagnostic evidence.

The corrected single-package diagnostic completed at
`C:\b\aipacs-internal-3.6.6-20260910-111348`. It built the latest accepted
Developer Run source as a non-promotable PyInstaller Standard installer in about
20 minutes. `build_status.json` records exit code 0 and `status: completed`.

| Internal artifact | Evidence |
|---|---|
| File | `source/builder/output/installer/ai-pacs standard v3.6.6.exe` |
| Size | 634,725,244 bytes; inside the documented 0.55-0.70 GB Standard band |
| SHA-256 | `E0F0AF80CB376D640A653F814263FF172453D70881DB04FC3EEB1D25E7270F49` |
| Windows metadata | FileVersion 3.6.6; ProductVersion 3.6.6 |
| Source identity | HEAD `78d53174615aeaadceb3f1352b4849ddbe1369bf` plus the recorded post-tag build-tool working tree; snapshot fingerprint `4aeee91045beb1f7a9a1de5defabf0e08577f54b76a3fcc60ef1e884c8ec1a16` |
| Content | Advanced MPR/Slicer required files present; offline Lumbar and Brain absent as required by Standard |
| Gates | Pre-build, frozen MPR, sanitized config, plugin package, codec metadata, education mirror, Lite Viewer frozen self-test, and Inno compile passed |

The x64 binary scan retained its documented warning for the third-party
`speech_recognition/flac-win32.exe`; it did not introduce a new failure. The
installer was not launched, installed, copied to the repository release folders,
signed, uploaded, or promoted.

## Output-routing correction

The successful file under `C:\b` is not a completed version 3.6.6 build. `C:\b`
is short-path compiler scratch space only; it is not a third installer hierarchy.
The earlier run was incorrectly reported as build completion even though it
produced only one non-promotable diagnostic file.

An unqualified owner request to make a build now means both backends and all three
editions. The coordinator records all six expected destination paths before it
starts compilation and writes final artifacts only to:

- `builder/output/installer`: PyInstaller Eagle Eye, Standard, and ARM64-emulated.
- `builder nuitka/output/installer`: Nuitka Eagle Eye, Standard, and ARM64-emulated.

The 2026-09-10 completed local install-QA run now places all three version 3.6.6
PyInstaller files in `builder/output/installer` and all three version 3.6.6 Nuitka
files in `builder nuitka/output/installer`. Backend-specific installation notes,
checksums, and distribution metadata were refreshed in those same folders. No
historical installer was renamed or reused as version 3.6.6.

## Remaining acceptance gates

These files are complete local installation-QA artifacts and can be installed for
testing. They have not been signed, uploaded, or promoted. Clean installation,
upgrade/uninstall/rollback, installed viewer and clinical checks, physical printing,
representative de-identified cardiac Flow re-import, and real Windows-on-ARM64
emulation remain separate acceptance activities. Any later public redistribution
must use the receipt-backed release lane and its publication approvals.

## Rollback

On failure, preserve the isolated candidate evidence and discard only that named
candidate when it is no longer needed. Do not alter previous installers, shared
Git history, or the immutable release tag.

## Pending source amendment for the next candidate (2026-09-13)

The EchoMind typography and pathology-organization changes were made after the
completed September 10 candidate above. They are **not claimed present in those
existing installers**. Include the current canonical `ai_chat_pages.py` and
`ai_chat_widgets.py` plus regenerated EchoMind payloads in the next authorized
candidate snapshot. The shared renderer covers all six current modalities and
specialty headings; ordered pathology, sentence breaks, margins and font scale
survive Reception export. Reporting and edition-stage checks: 164 passed, exit 0;
all 462 mirrors match. No new build or publication was performed for this change.
Details: `../echomind/REPORT_TYPOGRAPHY_2026-09-13.md`.
