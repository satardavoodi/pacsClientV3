# AI-PACS v3.6.6 release record

Release date: 2026-09-09
Release commit: resolved from the immutable annotated tag and Git synchronization receipt
Release tag: `v3.6.6`
Source branch: `beta-version`
Source publication status: READY
Production approval: NOT YET GIVEN

## Outcome and scope

Version 3.6.6 freezes all reviewed changes after v3.6.5 into a new source identity.
The release adds the complete printing maintenance sequence: off-GUI DICOM transport,
truthful submission status, study/page ownership, current-page regeneration, corrected
window/level and color handling, physical page sizing, selection behavior, diagnostic
capacity independent of Scout, a fixed 2x2 Scout, adaptive reference labels with stable
source numbering, and background-independent grid visibility.

The release retains the v3.6.5 mammography and lumbar/brain Eagle Eye integrations,
explicit EchoMind provider selection, viewer/import stability, Advanced MPR/Slicer
edition contents, DICOM codec/legal corrections, license protection, and cardiac MRI
Flow VM normalization for interoperability exports.

## Compatibility, migration, and stored data

- Existing printing configuration remains readable. Legacy fractional `scout_scale`
  values are intentionally replaced by the fixed 2x2 Scout policy.
- Rows x columns now means diagnostic-image capacity; Scout is additional. This can
  change page counts for the same selection but prevents image loss or hidden capacity.
- No database migration is introduced.
- Standard and ARM64-emulated editions retain Slicer and exclude Eagle Eye offline
  models. Eagle Eye retains Slicer plus approved Brain and Lumbar assets.
- ARM64-emulated means the x64 application running under Windows-on-ARM64 emulation;
  it is not a native ARM64 binary.

## Verification evidence

| Gate | Command or evidence | Result |
|---|---|---|
| Version parity | Project, main application, Information fallback, build default, and legal payload | PASS |
| Mandatory build and printing tests | Direct pytest selection, 216 passed, exit 0 | PASS |
| Plugin mirror parity | `tools/dev/verify_plugin_mirrors.py`, 462 pairs | PASS |
| Secret scan | Canonical release-manager tracked-tree scan | PENDING PUBLICATION AUDIT |
| Developer Run | Owner requested build from latest source; latest printing slice has no new recorded live run | ACCEPTED FOR CANDIDATE ONLY |
| Build environment | Both dependency checks, Python 3.13.5, PyInstaller 6.11.1, Nuitka 4.1.3, Inno Setup 6 | PASS |
| Distribution assets | 34,529 files / 4,329,814,502 bytes verified | PASS |
| Git synchronization | Receipt path and exact SHA | PENDING PUBLICATION |
| Installer matrix | Six files, sizes, hashes, and metadata | PENDING BUILD |
| Clean install / upgrade / rollback | Isolated Windows evidence | BLOCKED |

## Deliberate exclusions

Generated build state, checkpoints, compiler XML, runtime profile state, Python
bytecode, installers, logs, caches, credentials, clinical data, AI captures, and
local machine settings are excluded from the release commit. Historical build
outputs remain evidence and are never used as source.

## Known risks and blockers

1. Historical provider credential exposure still requires confirmed revocation,
   rotation, and repository-history remediation. Current-tree scanning does not
   close that incident.
2. Latest printing behavior is automated/offscreen verified but still needs source
   UI review, physical printer validation, and clinical layout acceptance.
3. Candidate installers require clean install, upgrade, uninstall, rollback,
   representative de-identified cvi42 cardiac Flow re-import, real ARM64-host
   testing, signing, legal review, and explicit owner approval before distribution.
4. The repository-wide historical fast lane remains unsuitable as release proof;
   focused direct tests and fail-closed build gates are authoritative.

## Rollback

Discard only the isolated 3.6.6 candidate if compilation or install QA fails. After
publication, correct shared branches with a reviewed revert/fix and a later patch
version. Never move the v3.6.6 tag, reset shared branches, or relabel older outputs.

## Approval

Source publication approved by: Repository owner request, 2026-09-09
Installer distribution approved by: NOT YET GIVEN
