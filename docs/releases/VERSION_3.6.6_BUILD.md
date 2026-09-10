# AI-PACS 3.6.6 build record

Status: INTERNAL STANDARD PASSED; OFFICIAL MATRIX BLOCKED
Date: 2026-09-10

## Requested matrix

The repository owner requested a new version 3.6.6 build containing the latest
reviewed changes. The canonical coordinator must create six installers from one
clean, synchronized, receipt-backed commit:

- PyInstaller: Eagle Eye, Standard, ARM64-emulated.
- Nuitka: Eagle Eye, Standard, ARM64-emulated.

Final files belong only in `builder/output/installer` and
`builder nuitka/output/installer`. ARM64-emulated is x64-on-ARM64 and is not a
native ARM64 build.

## Source and preflight evidence

- Exact release commit and receipt: pending canonical publication.
- Version authorities: 3.6.6.
- Mandatory build and printing selection: 216 passed, 6 third-party SWIG
  warnings, exit 0.
- Plugin mirrors: 462 pairs match.
- Runtime and build dependency checks: pass.
- Toolchain: Python 3.13.5, PyInstaller 6.11.1, Nuitka 4.1.3, Inno Setup 6.
- Distribution assets: 34,529 files / 4,329,814,502 bytes verified.
- Candidate-drive free space: more than the required 60 GiB.

## Artifact evidence

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

The corrected one-command run completed at
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

## Remaining acceptance gates

Candidate generation is not production approval. Signing, clean installation,
upgrade/uninstall/rollback, installed viewer and clinical checks, physical printing,
representative de-identified cardiac Flow re-import, real Windows-on-ARM64 emulation,
legal confirmation, credential-incident remediation, and explicit owner sign-off
remain open.

The official six-installer matrix additionally remains blocked until the release
owner supplies real Brain redistribution evidence in the documented approval file.
Local runtime success is not legal redistribution approval, and the gate must not
be bypassed.

## Rollback

On failure, preserve the isolated candidate evidence and discard only that named
candidate when it is no longer needed. Do not alter previous installers, shared
Git history, or the immutable release tag.
