# AI-PACS v3.6.8 release

Release date: 2026-09-26
Release commit: resolved from the immutable annotated tag and Git synchronization receipt
Release tag: `v3.6.8`
Source branch: `beta-version`
Source publication status: READY
Production approval: NOT YET GIVEN

## Outcome and scope

The owner requested the latest DICOM workstation Client source, publication to
all three configured repositories, and four Client installers: Standard and
x64-on-ARM64-emulated editions from PyInstaller and Nuitka. No Server installer
is requested. Shared source includes the remote Eagle Eye role boundary, grouped
Settings navigation, guarded viewer and thumbnail identity/lifecycle updates,
download transport fixes, EchoMind command routing and the corrected native
Advanced Viewer packaging contract. Server source may be present in the shared
repository; publishing it does not qualify a Server installer or clinical model.

## Compatibility, migration, and stored data

Application and Information fallback report 3.6.8. Installer metadata derives
from pyproject.toml. The Python presentation overlay reports 3.6.8 while reusing
the hash-verified native Slicer executable documented in
../release-and-build/SLICER_NATIVE_BASELINE_2026-09-23.md. Standard and ARM exclude
Server model weights. ARM is x64-on-ARM64 emulation, not a native ARM64 binary.
Preserve local settings, certificates, credentials, clinical data and historical
installer outputs. Cardiac Flow normalization and DICOMDIR remain required.

## Verification evidence

| Gate | Evidence | Result |
|---|---|---|
| Build interpreter | .venv_build pip check | PASS, 2026-09-26 |
| Plugin mirror parity | verify_plugin_mirrors.py, 472 matching pairs | PASS, 2026-09-26 |
| Current tracked-tree secret scan | Canonical path-only scanner, no findings before staging new source | PASS; staged-tree audit still required |
| Version and focused packaging guards | Direct pytest, 171 passed; exit 0 | PASS |
| Eagle Eye configuration isolation and role checks | Two fail-before sanitizer guards; 20 related tests passed after; exit 0 | PASS |
| Changed-code diagnostic suite | 827 passed, 1 xfailed, 3 failed; the owned role expectation was corrected with 43 passing tests, two pre-existing spinner doubles remain | KNOWN BASELINE FAILURES; NOT GREEN |
| Distribution cache | 34,459 files / 4,309,450,168 bytes verified, exit 0 | PASS |
| Native Slicer/cache parity | verify_cache_matches_developer_runtime, exit 0 | PASS |
| Git/identity/Settings/presentation checks | Additional 60 direct tests passed, exit 0 | PASS |
| Standard MPR VRT receipt | Owner's completed 69-test record plus 5 direct local VRT guards, exit 0; fresh source GUI pending | CODE VERIFIED; NOT CLINICALLY ACCEPTED |
| Git synchronization | Exact commit, tag and three-remote receipt | PENDING |
| Installer matrix | Four Client files, resources, hashes and coherence | PENDING |
| Clean install, upgrade, ARM64 and clinical GUI | Isolated host and human acceptance | NOT RUN |

## Deliberate exclusions

Local connection/profile/sort/viewer configuration, pairing material, runtime
profiles, bytecode, installers, immutable caches, native runtime backups,
clinical data, logs and private review evidence are not release source.

## Known risks and blockers

The historical credential incident remains open until rotation/history
remediation is independently confirmed. A clean current-tree scan does not close
that incident. Repository-wide fast-lane confidence is not claimed. Several
runtime workstreams retain their documented source GUI/clinical gates. Frozen
service packaging is unqualified and is not part of this Client build. Installer
signing, legal redistribution, clean-host lifecycle, real ARM64 and clinical
acceptance remain required before production distribution.

The changed-test diagnostic run exposed two already documented spinner-double
failures: the expected overlay call omits `opaque_native_background`, and the
fallback stub lacks `repaint`. The runtime is unchanged from HEAD; the VTK owner
report previously reproduced both against unmodified HEAD test text. Neither
test was removed, quarantined or called a pass. Their correction remains with
the Viewer owner. The development `builder/output/stage` also predates the new
Eagle Eye template and current echo/modality/printing defaults; no generated
stage was edited. A new candidate must generate and validate its own stage.

## Rollback

Preserve previous installers and local configuration backups. Restore the prior
qualified installer and its documented settings/data backup if installation QA
fails. Shared Git history is reverted with a reviewed commit; published tags
must never be moved or force-pushed. Resume only an identical candidate using
the canonical coordinator; a changed source requires a new reviewed identity.

## Approval

Source publication approved by: owner, explicit request on 2026-09-26
Installer compilation approved by: owner, four Client outputs only
Installer distribution approved by: NOT YET GIVEN
