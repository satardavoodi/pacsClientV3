# AI-PACS v3.7.1 Standard Client release

Release date: 2026-10-06
Release commit: resolved from the immutable annotated tag and Git synchronization receipt
Release tag: `v3.7.1`
Source branch: `beta-version`
Source publication status: READY
Production approval: NOT YET GIVEN

## Outcome and scope

The owner requested latest-source Git publication and exactly four Standard
Client installers. Use the next patch version because v3.7.0 is already
published; do not move that tag. Shared source changes since v3.7.0 cover Home
catalog/thumbnail convergence, EchoMind Assist/history and Secretary control,
Support diagnostics, patient workflow/realtime coordination, portable media
readiness, stored Brain/Alignment results, demographic/report handling and MPR
geometry. Do not infer clinical acceptance from source tests.

The owner confirmed the latest working source as the build input on October 6
and specifically requested inclusion of the `fix 2` DICOM correction. Complete
encapsulated Pixel Data ending at EOF can be recovered without rewriting the
original file when only the final sequence delimiter is missing; actually
truncated or malformed items remain rejected. The pure reader is explicitly
retained by both frozen cores and all three viewer mirrors are synchronized.

There is no Eagle Eye Server compilation, model bundle deployment, Razi service
change, automatic application launch or clinical installation in this task.

## Build contract

Follow RELEASE.md, then BUILD.md and tools/build/build_local_candidate.py.
Select Client, both backends, with a fresh receipt for the clean exact commit.
Explicitly select the immutable
generated-files/distribution-assets-native-vc143-vmtk-service-20260928 cache.
Reuse its native custom Slicer/VMTK; overlay current snapshot Python/UI files.
Do not rebuild Slicer or substitute an older runtime.

Final requested files, only in their established folders:

- builder/output/installer/ai-pacs standard v3.7.1.exe
- builder/output/installer/ai-pacs arm64-emulated v3.7.1.exe
- builder nuitka/output/installer/ai-pacs standard v3.7.1.exe
- builder nuitka/output/installer/ai-pacs arm64-emulated v3.7.1.exe

ARM means the x64 workstation on Windows ARM64 emulation, not a native ARM
binary. C:/b is compiler scratch and evidence, never a deliverable location.

## Compatibility, migration, and stored data

Keep current Settings/Client role boundaries, hidden Slicer warm-up, lumen
workspaces, Qt/ICU hygiene, codecs, legal notices, Lite Viewer, Cardiac Flow
VM normalization and DICOMDIR handling. Standard/ARM exclude offline Eagle Eye
models and model interpreters. No live data or machine configuration is migrated
by source publication or compilation. Existing routing gaps remain documented
in the EchoMind routing record; do not claim all legacy paths are migrated.

## Verification evidence

| Gate | Evidence | Result |
|---|---|---|
| Initial packaging selection | Direct pytest, 15 release/packaging families | 156 passed, three shared-page mirror failures; exit 1 |
| Mirror correction | Scoped synchronizer and verifier | 512 pairs match; exit 0 |
| Post-correction adjacent checks | Distribution, payloads, Assist, timestamps, reception conflict, history | 63 passed; exit 0 |
| Initial affected-source selection | 16 workflow/source families | 400 passed; exit 0 |
| Expanded changed-source selection | 97 changed automated guard files; excludes opt-in live tests and separate Breast research | 1216 passed, three failed, one skipped; exit 1 |
| Secretary guard maintenance | Re-anchor two outdated structural guards to existing extracted callback and add five behavioral cases | 28 passed; exit 0; runtime logic unchanged |
| Expanded re-run after guard maintenance | Same 97 files; no test deselected or disabled to hide the remaining failure | 1223 passed, one unchanged Server prompt-parity failure, one host-symlink skip; exit 1 |
| Build environment | .venv_build pip check | No broken requirements; exit 0 |
| Immutable asset inventory | Full prepare_distribution_assets.py --check --profile all | 34,469 files, 4,356,143,152 bytes; exit 0 |
| Version parity | Project, main application, Information fallback, legal applicability | All source authorities 3.7.1; 159 post-version packaging guards passed, exit 0; installer resource verification awaits compilation |
| Changed-source syntax / whitespace | Parse changed/new non-generated Python and git diff --check | 360 Python files parse; no diff whitespace errors |
| Current tracked-tree secrets | Redacted path-only scanner after deliberate staging | No high-confidence findings; protected research directory false positives corrected with fail-before guards, without document allowlisting or disabling scans |
| DICOM EOF compatibility | Direct viewer, codec and import pytest selection | 53 passed; exit 0 |
| Explicit DICOM core retention | New builder guard, before/after spec enrollment | Two failed and one passed before; 18 builder/reader cases passed afterwards, exit 0 |
| Final Client packaging selection | 17 families including EOF reader and VM normalization; direct pytest | 188 passed, exit 0; 6 dependency deprecation warnings |
| Git publication guards | Direct pytest of release manager and token-boundary cases | 18 passed, exit 0 |
| Publication source review | Deliberately staged source/docs/synthetic fixtures; no broad add | 562 files, including 374 parseable Python files; staged whitespace clean and tracked-tree high-confidence scan empty |
| Developer input acceptance | Owner October 6 confirmation of latest source plus fix 2 | Accepted as candidate input; not a new live viewport or installed acceptance pass |
| Git synchronization | All six remote refs and three annotated tag objects | Pending 3.7.1 audit/publication/receipt |
| Four artifacts | Backend exits, coherence, contents, independent hashes and version resources | Pending |
| Installed acceptance | Clean install, upgrade, uninstall, rollback, actual ARM64 host and clinical workflows | Pending |

## Shared-page parity handoff

One canonical shared page differed from its packaged mirror. The source was
last written on September 30 at 15:48 and the mirror at 14:24. Reviewed differences
cover Assist context, reference retry snapshots, message timestamps and
generation-bound callbacks. This release task copied only that source file
using the existing scoped tool. It did not implement another runtime fix.
The prior owner routing report retains its historical pending handoff; this
dated parity evidence does not manufacture live GUI or server acceptance.

## Previous interruption

The preserved v3.7.0 workspace is
C:/b/aipacs-3.7.0-20260930-client-r2. PyInstaller completed with exit 0;
Nuitka's last log at September 30 15:52 was Standard Inno compression, and the
host last booted at 15:58. Its recorded process is no longer present. This is
consistent with interruption by reboot, not evidence of a completed matrix.
The two old PyInstaller files and old tag remain untouched. Changed inputs and
a new version require a fresh candidate, not old-core reuse or file renaming.

## Deliberate exclusions

Exclude machine-local config changes, generated-files/runtime_profile.json,
generated probes, images, PDFs, DICOM, logs, private research/recovery state,
credentials, pairing material, compiled outputs, caches and model weights.
Only reviewed source, synthetic fixtures and curated documentation may enter
Git. Preserve excluded working bytes recoverably and restore them after the
immutable snapshot; do not delete or broadly stash unrelated source work.

## Known risks and blockers

An initial packaging re-run timed out inside a network fetch invoked by a
codec guard. The final 188-test run explicitly uses the existing
`AIPACS_SKIP_GIT_FETCH=1` unit-test setting, with no tests removed; this is not
online freshness evidence. Publication still requires the release manager's
separate online audit and exact six-branch/three-tag verification.

Expanded verification found a Server long-prompt parity failure in
test_eagle_eye_echomind_core.py. Both openai_reporter.py copies are byte-for-byte
unchanged since published v3.7.0 HEAD, where their parsed long literal parity
also fails. No Server prompt was changed or normalized by this Client task.
Keep that failure visible and pending with the Server owner; do not weaken the
guard, count it as passing, or claim a Server release. The two other failures
were July Secretary guards anchored to the old pre-extraction method; their
updated structural and behavioral tests preserve the original invariants.

Current-tree scanning is not remediation of the historical credential incident.
Rotation/history cleanup remains open. Installed viewer/clinical checks,
external Cardiac Flow consumers, ARM64 emulation, signing, legal redistribution
and upgrade/rollback remain independent gates. No production promotion is
authorized while these remain unresolved. A source test pass or the source
being present in a snapshot is not proof of frozen installer behavior.

## Rollback

Keep old installers, caches and candidate evidence. Shared Git rollback uses
a reviewed revert/new patch release, never a tag move or force-push. Before
human-operated installed QA, retain prior installer and back up host data and
configuration, then verify rollback outside clinical work.

## Approval

Source publication approved by: repository owner, explicit current request
Installer compilation approved by: repository owner, four Standard Client files
Latest Developer input acceptance: repository owner, 2026-10-06, latest source plus fix 2
Installer distribution / production approval: NOT YET GIVEN

## Current handoff

This source record approves publication input, not production distribution.
The release SHA is resolved from the immutable tag and generated synchronization
receipt. Compiler and artifact status belongs to the candidate's generated
build_status.json and final backend metadata; neither is fabricated in advance.
At source freeze, all tests and scans above are complete; Git synchronization
and compilation remain the next steps. Eight local settings files have verified
exact-byte private backups. Generated/private untracked evidence stays in place
under local Git exclusions; it is not deleted or committed. Temporarily preserve
only the eight local settings for the clean publication/snapshot gate, then
restore their exact bytes once the immutable input is captured. Preserve prior
installers. Inspect the resulting frozen inventories for the EOF reader before
claiming the fix is included in newly compiled installers.
