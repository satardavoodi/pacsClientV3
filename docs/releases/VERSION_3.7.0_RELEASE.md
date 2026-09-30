# AI-PACS v3.7.0 Standard Client release

Release date: 2026-09-30
Release commit: resolved from annotated v3.7.0 and the Git synchronization receipt
Release tag: `v3.7.0`
Source branch: `beta-version`
Source publication status: READY
Production approval: NOT YET GIVEN

## Outcome and scope

The owner explicitly requested source publication to all three configured Git
repositories followed by four Standard Client installers. The owner confirmed
the current Developer Client as accepted build input and stated that Client
development is no longer changing. This is not a Server build request.

The reviewed working-source inventory includes:

- Education authoring lists, asynchronous tasks, source selection, previews,
  portable course transfers, presentation and video/navigation handling.
- Home search/paging, exact study scope, thumbnail convergence and multiframe
  repair, Structured Report cards/viewing and attachment retry identity.
- CurveMPR path/VR controls and the current customized Advanced Slicer runtime,
  hidden warm-up, launch/import diagnostics, close/reopen handling, Vascular and
  Virtual Bronchoscopy workspaces and VMTK integration.
- EchoMind client routing to server-owned processing, consultation controls and
  shared Eagle Eye server/brain source changes. These remain in shared source;
  no Server installer or Server clinical acceptance is claimed by this release.
- Packaging parity, role-scoped output preservation, current legal notices and
  distribution-asset verification changes since the last published source.

## Build contract

Use only RELEASE.md followed by BUILD.md and
tools/build/build_local_candidate.py, target client, both backends. Obtain a
fresh receipt for the exact clean release commit before snapshot creation.
Use the immutable distribution-assets-native-vc143-vmtk-service-20260928 cache.
Reuse its verified native Slicer; overlay current snapshot Python/UI payloads.
Do not rebuild native Slicer or select the older cache without VMTK.

Produce exactly these four files in the established folders:

- builder/output/installer/ai-pacs standard v3.7.0.exe
- builder/output/installer/ai-pacs arm64-emulated v3.7.0.exe
- builder nuitka/output/installer/ai-pacs standard v3.7.0.exe
- builder nuitka/output/installer/ai-pacs arm64-emulated v3.7.0.exe

ARM64-emulated means the x64 Client under Windows ARM64 emulation, not a native
ARM64 executable. C:/b is isolated compiler scratch and evidence, never a new
deliverable destination. A version change requires fresh cores; reuse verified
assets and compiler caches, not a 3.6.9 frozen executable.

## Compatibility, migration, and stored data

Retain the Client/Server role boundary, current app-local VC143 DLLs, legal
notices, Qt/ICU hygiene, codecs and the Lite Viewer. Standard/ARM Clients include
Advanced Slicer/lumen workspaces but exclude offline Eagle Eye models and model
interpreters. Preserve Cardiac Flow VM normalization and DICOMDIR guards.
No live database, local credentials, paired server settings or clinical data are
migrated by source publication or installer compilation.

## Verification evidence

| Gate | Evidence | Result |
|---|---|---|
| Version parity | Project, main application, Information fallback, legal applicability | Updated to 3.7.0; installer resource verification pending compilation |
| Initial packaging selection | Direct pytest; packaging, Qt/ICU, codec, legal, ARM parity, lumen, Flow, Lite Viewer, credential obfuscation | 160 passed; exit 0 |
| Accepted Client scope | Direct pytest; Education, lumen/Slicer lifecycle, CurveMPR, Home/search/SR, attachment retry and remote backend | 362 passed, one existing quarantined xfail; exit 0 |
| Post-version release selection | Direct pytest; version/build contracts, asset refresh, EchoMind boundary and attachment sync | 149 passed; exit 0 |
| Plugin mirrors | verify_plugin_mirrors.py | 495 pairs match; exit 0 |
| Build environment | .venv_build pip check | Passed; no broken requirements |
| Immutable asset inventory | prepare_distribution_assets.py --check --profile all | 34,469 files, 4,356,143,152 bytes verified; exit 0 |
| Current-tree secret scan | release_manager path-only scan | No high-confidence findings; scan new staged inputs again before commit |
| Developer Client | Explicit owner acceptance in this chat | Accepted as build input; installed acceptance is separate |
| Git synchronization | Online release-manager verification and exact receipt | Pending publication; required before snapshot |
| Installer matrix | Backend exits, coherence, hashes, version resources and profile inventories | Pending; do not claim files complete yet |
| Clean install / upgrade / rollback / ARM64 host | Isolated installed-artifact evidence | Pending |

## Deliberate exclusions

Exclude all machine-local config changes, runtime_profile.json, generated
probes/images/DICOM fixtures, logs, certificates, pairing tokens, compiled
outputs, external caches and private recovery files from the release commit.
Temporarily preserve excluded working files recoverably for clean release
audit/snapshot, then restore their exact original bytes. Do not delete them.
The Server role, model bundle redistribution and Razi deployment are excluded.

## Known risks and remaining gates

Current-tree scanning is not remediation of the historical credential incident.
Rotation/history remediation remains open and must not be described as completed.
Installed clean-host, real ARM64-host, clinical compatibility (including external
Cardiac Flow consumers), code signing, legal/model distribution approval and
upgrade/uninstall/rollback acceptance are independent production gates.
The safety record keeps production promotion blocked until these are verified;
source publication and candidate compilation do not grant that approval.
Do not count Server Developer/service probes as Client artifact acceptance.

## Rollback

Retain prior versioned installers and v3.6.8 source/tag. For source rollback,
create a reviewed revert commit and a new patch release; never move tags or
force-push shared branches. Before installing this candidate on any clinical
host, preserve its data/configuration, retain the previous installer, and prove
restore/upgrade rollback in isolation. This task does not install it on a host.

## Approval

Source publication approved by: repository owner, explicit request in this chat
Build input approved by: repository owner, latest Standard Developer Client
Installer compilation approved by: repository owner, four Client outputs
Installer distribution / production approval: NOT YET GIVEN
