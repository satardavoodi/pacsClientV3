# AI-PACS v3.6.7 local install-QA build

Build date: 2026-09-21
Source branch: `beta-version`
Build lane: local install-QA
Publication status: NOT PUBLISHED
Production approval: NOT GIVEN

## Outcome and scope

This record covers the completed six-installer v3.6.7 local install-QA candidate.
Both packaging backends consumed the same immutable snapshot of the requested
development state. The canonical matrix is:

| Backend | Eagle Eye | Standard | x64 on ARM64 emulation |
|---|---:|---:|---:|
| PyInstaller | COMPILED | COMPILED | COMPILED |
| Nuitka | COMPILED | COMPILED | COMPILED |

The only final output locations are:

- `builder/output/installer`
- `builder nuitka/output/installer`

Scratch workspaces under `C:\b` and temporary packaging staging under
`C:\ap-stage` are not additional product output locations.

## Source state

The user requested a build of the latest development state while the repository
contains extensive tracked and untracked work. The coordinator therefore creates
one content-addressed snapshot and builds both backends from that exact snapshot.
This candidate is suitable for local installation QA only. It must not be represented
as a clean, synchronized, reproducible source release until the complete reviewed
scope is committed and a fresh Git synchronization receipt exists for that commit.

Candidate evidence:

- Workspace: `C:\b\aipacs-internal-3.6.7-20260921-143614`
- Git branch and recorded HEAD: `beta-version`, `3f0d6a1a18`
- Snapshot source SHA-256: `c2b571e180eee4a5aeffd89862e963c3f9514d75ede4bc6d80d3ce9ecda7cd6f`
- Python: `3.13.5`
- Nuitka: `4.1.3`
- Compiler: MSVC, serial low-memory release profile

The first two candidate attempts exposed missing external Alignment and Total Spine
source forwarding/materialization. A third attempt exposed a Nuitka 4.1.3/Python
3.13 async-`finally` comprehension assertion. The final candidate then survived an
interrupted Stage 10 by using the same-candidate recovery route. PyInstaller was
retained, Nuitka resumed only Stage 10, and cross-backend coherence was rerun. No
failed or partial installer was promoted.

## Verification evidence

| Gate | Evidence | Result |
|---|---|---|
| Version parity | `pyproject.toml`, application metadata, Information panel, Advanced Viewer title, and all installer version resources report 3.6.7 | PASS |
| Python environment | `.venv_build` dependency check: no broken requirements | PASS |
| Plugin mirror parity | 470 pairs matched; 0 plugin-only files | PASS |
| Distribution assets | 34,529 files / 4,329,814,502 bytes verified | PASS |
| Focused packaging tests | 144 passed, 6 existing SWIG deprecation warnings, exit 0 | PASS |
| Cardiac Flow interchange | VM-normalization/DICOMDIR tests passed; PyInstaller archive and Nuitka XML both contain `dicom_vm_normalization` and `modules.dicom_media.dicomdir` | PASS |
| Snapshot coherence | Both backends used source SHA-256 `c2b571...da7cd6f`; coherence exit 0 | PASS |
| Installer matrix | Six exact files; independent sizes, hashes, and Windows versions match generated metadata | PASS |
| Code signing | All six installers are `NotSigned` | NOT READY FOR PUBLIC DISTRIBUTION |
| Clean install / upgrade / uninstall | Isolated Windows host | NOT RUN |
| Real ARM64 host | Microsoft x64 emulation on ARM64 | NOT RUN |
| Clinical acceptance | Representative de-identified workflows | NOT RUN |

## Security and distribution boundary

The repository security audit records unresolved credential-shaped source history.
No secret values may be copied into this record. This local build does not authorize
Git publication, installer upload, public distribution, or production promotion.

## Artifact evidence

| Backend | Edition | Filename | Bytes | SHA-256 |
|---|---|---|---:|---|
| PyInstaller | Eagle Eye | `ai-pacs eagle-eye v3.6.7.exe` | 1,785,526,154 | `BEA3185EBB1DA80E0B588DE505470E8581352D558F2AE98CD1F343C820B1988B` |
| PyInstaller | Standard | `ai-pacs standard v3.6.7.exe` | 635,475,974 | `56B6CACC8345DF36F8F62602D9009388575C89CBB2B41EAE185E141EC0A32928` |
| PyInstaller | x64 on ARM64 emulation | `ai-pacs arm64-emulated v3.6.7.exe` | 635,476,107 | `27C98122B731A46910C48F83659FFFF860283AD9FF9233A64713135883C2E5C9` |
| Nuitka | Eagle Eye | `ai-pacs eagle-eye v3.6.7.exe` | 1,749,308,055 | `F7C8783331E77E979DF80F1F974073DB88B090DF0838F79206BFA79DF7FAB383` |
| Nuitka | Standard | `ai-pacs standard v3.6.7.exe` | 599,265,245 | `F82443F524805F907C1900E0BC41003201BEE305C6F2917B79C74B18B6FBB5F8` |
| Nuitka | x64 on ARM64 emulation | `ai-pacs arm64-emulated v3.6.7.exe` | 599,265,466 | `7D367046058C402886544EDCCDC8010513C03D25D2AD29F9525AD4114E0DE8C5` |

Every row independently reports Windows FileVersion and ProductVersion `3.6.7`.
The generated backend metadata and `SHA256.txt` files contain the same sizes and
digests. The coordinator records `status: completed`, both backend exit codes are
zero, Nuitka stages `0, 6, 7, 8, 9, 10` are complete, and `coherence_exit_code` is
zero.

Final output locations:

- PyInstaller: `builder/output/installer`
- Nuitka: `builder nuitka/output/installer`

The workstation and installers were not launched during this build. Runtime,
installation, upgrade, uninstall, clinical, and real ARM64 acceptance remain
separate human/isolated-host gates.

## Rollback

Do not overwrite an accepted installation during build verification. Validate in an
isolated environment, retain the previous accepted installers, and uninstall the
candidate before restoring the earlier version. Shared Git branches are rolled back
with a reviewed revert commit; tags and published history are never moved.
