# AI-PACS 3.6.6 build record

Status: PREPARING SYNCHRONIZED-SOURCE CANDIDATE
Date: 2026-09-09

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

The coordinator will append or supersede this preparation section with the exact
candidate workspace, toolchain, elapsed time, file sizes, SHA-256 values, Windows
version metadata, and coherence result after compilation. No 3.6.5 installer may
be renamed, copied, resumed, or promoted as 3.6.6.

## Remaining acceptance gates

Candidate generation is not production approval. Signing, clean installation,
upgrade/uninstall/rollback, installed viewer and clinical checks, physical printing,
representative de-identified cardiac Flow re-import, real Windows-on-ARM64 emulation,
legal confirmation, credential-incident remediation, and explicit owner sign-off
remain open.

## Rollback

On failure, preserve the isolated candidate evidence and discard only that named
candidate when it is no longer needed. Do not alter previous installers, shared
Git history, or the immutable release tag.
