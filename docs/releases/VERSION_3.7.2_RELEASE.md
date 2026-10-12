# AI-PACS v3.7.2 Standard Client candidate

Release date: 2026-10-09
Release commit: NOT PUBLISHED; resolve exact local input from build_source_manifest.json
Release tag: NOT CREATED
Source branch: beta-version
Source publication status: BLOCKED
Production approval: NOT YET GIVEN

## Outcome and scope

The owner requested four Client installers at version 3.7.2. After being told
that the shared Eagle Eye candidate still blocks build handoff, the owner
explicitly directed freezing the current package and starting Client builds,
with continuing changes confined to Eagle Eye Server. This is a one-run
Client compilation exception, not a change to the standing Developer parity
policy and not approval to activate or deploy a Server candidate.

Use BUILD.md's existing local install-QA lane and the canonical coordinator.
Capture the current working source, including required untracked source and
packaged mirrors, into one sanitized, content-addressed immutable snapshot.
Both backends use that same input. Later development changes are excluded.
The source checkout and its private configuration remain preserved.

No runtime bug fix is implemented by this packaging task. Shared source present
in a Client snapshot is not a Server release or validation of all AI functions.

## Build contract

Command: .venv_build/Scripts/python.exe tools/build/build_local_candidate.py
--local-install-qa --target client
--asset-root generated-files/distribution-assets-native-vc143-vmtk-service-20260928

Final deliverables, only in the established folders:

- builder/output/installer/ai-pacs standard v3.7.2.exe
- builder/output/installer/ai-pacs arm64-emulated v3.7.2.exe
- builder nuitka/output/installer/ai-pacs standard v3.7.2.exe
- builder nuitka/output/installer/ai-pacs arm64-emulated v3.7.2.exe

ARM64-emulated is x64-on-Windows-ARM64, not native ARM64. Both backends compile
fresh cores for the new version and run sequentially. Reuse the verified custom
Slicer/VMTK native cache and overlay the frozen current Python/UI payloads.
Do not rebuild Slicer, reuse an old-version core, or create Server editions.

## Compatibility, migration and stored data

Preserve codecs, DICOM EOF compatibility, cardiac Flow VM normalization,
DICOMDIR, Lite Viewer, Qt/ICU hygiene, hidden Slicer warm-up, lumen workspaces,
role-aware Settings, license verification and legal notices. Per-host settings
are sanitized only inside the snapshot. No database or clinical data migration,
automatic installed executable launch or service transition is authorized.

## Verification evidence

| Gate | Evidence | Result |
|---|---|---|
| Owner input selection | Explicit instruction to freeze current Client package and start four builds | Accepted for local compilation, not production |
| Mirror parity | tools/dev/verify_plugin_mirrors.py, direct exit 0 | 528 matching pairs, zero plugin-only files before freeze |
| Build environment | .venv_build python -m pip check, direct exit 0 | No broken requirements |
| Native/assets | Client inventory and Developer/native parity checks, direct exit 0 | Cache manifest: 34,469 files / 4,356,143,152 bytes; assembled Developer/native parity passed |
| Version authorities | Project, main application, Information fallback, legal applicability | Updated to 3.7.2; automated guards pending |
| Focused packaging guards | Direct pytest, no wrapper; test-only Git-fetch isolation | 169 passed, exit 0; six dependency deprecation warnings |
| Adjacent Client/native/security guards | Client sanitization, license boundary, VMTK, asset preparation and lumen tests | 32 passed, exit 0 |
| Client identity/AI/Settings guards | Automatic/Windows human sessions, Single Send, shared AI and Settings groups | 55 passed, exit 0; six dependency deprecation warnings |
| Secret signatures | Redacted path-only release scanner on development tracked tree and full captured candidate | Zero high-confidence findings in both; historical remediation remains separate |
| Snapshot identity | C:/b/aipacs-client-3.7.2-20261009-r1/source/build_source_manifest.json | 8,514 sanitized input files; source SHA-256 ba42fa158f4952f62f1675b7733a822e063db4b523fe1b37a44f01e07aa78ad1 |
| Four artifacts | C:/b/aipacs-client-3.7.2-20261009-r1/build_status.json; independent file checks on 2026-10-10 | Both backends completed, coherence exit 0; four files verified. Local QA only, installed acceptance pending |
| Git publication | No new release commit/tag or fresh multi-remote receipt | Not performed; local QA only |
| Razi parity/activation | Latest user-auth receipt explicitly blocks handoff | Not qualified; owner-directed Client-only compilation exception |
| Installed acceptance | Clean install, upgrade/uninstall/rollback, real ARM64 host and clinical workflows | Pending |

## Deliberate exclusions

Exclude future Server edits after snapshot freeze, Server installers, offline AI
model/runtime bundles, host-private credentials and license stores, patient data,
databases, logs, runtime profiles, generated probes, compiler outputs and caches
from source inputs. Configuration sanitization preserves Developer configuration
unchanged while removing center-specific values from the candidate.

## Known risks and blockers

The latest authentication/shared-AI Server candidate is inactive; required payload
parity and live upstream/GUI acceptance remain pending. This local build does not
clear them. New source integration is not equivalent to successful requests
against the currently running Razi service. Historical credential rotation and
history remediation, clinical/GUI acceptance, real ARM64 testing, legal review,
signing and installed lifecycle verification remain open. Do not distribute or
label these candidates production-ready merely because compilation succeeds.

## Rollback

Preserve old installers, immutable asset caches and prior candidate evidence.
The coordinator preserves prior selected QA outputs in the existing _superseded
folder when necessary. Before installed QA, the human retains the previous
installer and backs up host data/configuration. No shared Git history is changed.

## Approval and continuation

Installer compilation approved by: repository owner, 2026-10-09, current package
freeze and four Client outputs despite pending Server handoff.
Source publication approved by: NOT PERFORMED in this local candidate task.
Installer distribution / production approval: NOT YET GIVEN.

The coordinator status and immutable manifest are authoritative for source hashes,
backend progress and artifact completion. Resume interruptions only through
BUILD.md's --resume-workspace workflow; never modify the captured source to admit
later Server changes. Update actual test and artifact evidence before reporting
completion; pending rows are not passes.

## Started candidate

The prepare-only coordinator completed with exit 0. The same canonical
coordinator was started with --run-prepared, --local-install-qa, --target client
and both recorded backends. Its workspace is
C:/b/aipacs-client-3.7.2-20261009-r1. Read build_status.json there for the actual
backend state; coordinator.stdout.log and coordinator.stderr.log preserve the
launcher output. These paths are scratch/evidence, not installer destinations.
The versioned source record was updated after freeze to report actual evidence;
this documentation-only update does not alter the captured compiler input.
