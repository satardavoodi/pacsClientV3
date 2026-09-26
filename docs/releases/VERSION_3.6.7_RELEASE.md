# AI-PACS v3.6.7 release record

Release date: 2026-09-21
Release commit: resolved from the immutable annotated tag and Git synchronization receipt
Release tag: `v3.6.7`
Source branch: `beta-version`
Source publication status: READY
Production approval: NOT YET GIVEN

## Outcome and scope

Version 3.6.7 freezes the reviewed workstation, Eagle Eye, EchoMind, viewer,
storage, download, packaging, and release-workflow changes accumulated after
v3.6.6 into one source identity. The release includes the unified
patient/study/series presentation and cache-lifecycle work, viewer stability and
startup safeguards, Eagle Eye mammography, lumbar, brain-lesion, Alignment,
Total Spine, dataset, and workspace integrations, EchoMind template and protected
provider-key handling, Advanced Viewer/Slicer presentation work, and the canonical
six-installer build workflow.

This six-installer matrix records the historical 3.6.7 build. New build requests
use the role-selected four-file Client or two-file Eagle Eye Server route in
`BUILD.md`; this record is not a command to rebuild all six.

**Installed Advanced Viewer correction, 2026-09-22:** the existing local 3.6.7
installers predate the latest `presentation.py` source and the frozen resident
warm-up resource-path correction. The installed Advanced MPR package on the
development PC contains the older presentation, even though its product version
is 3.6.7. These historical installers are not evidence of the current UI and
must not be promoted as the corrected build. A fresh role-selected candidate,
installation, and visible warm-up/UI acceptance are required after source freeze.

The completed local build also retains the cardiac MRI Flow VM-normalization and
DICOMDIR interoperability modules in both frozen backends. This record authorizes
source publication only; it does not authorize installer distribution or production
promotion.

## Compatibility, migration, and stored data

- Project, application, Information panel, installer resources, and Advanced Viewer
  branding use version 3.6.7.
- No destructive database migration is introduced.
- Existing local data remains under the documented storage and cleanup contracts.
- Standard and ARM64-emulated editions include the approved Slicer runtime without
  the Eagle Eye offline model set. Eagle Eye includes the approved model payloads.
- ARM64-emulated means the x64 application running through Windows-on-ARM64
  emulation; it is not a native ARM64 binary.

## Verification evidence

| Gate | Command or evidence | Result |
|---|---|---|
| Version parity | Project, main application, Information fallback, build defaults, Advanced Viewer, and installer metadata report 3.6.7 | PASS |
| Changed-code regression selection | Direct pytest selection; 1,904 passed, 1 environment-only symlink skip, 1 deselected, 6 existing SWIG warnings; heavyweight Alignment distribution fixture and order-sensitive WebEngine Qt file validated separately | PASS |
| Focused release corrections | Legion Consult catalog, Advanced Viewer version, and isolated WebEngine notice tests; 28 passed | PASS |
| Local Eagle Eye engine safety | Qualified-bundle routing, manifest revision binding, Breast stacker-schema rejection, source inventory, attachment routing, and worker guards; 18 passed | PASS |
| Focused packaging tests | 144 passed; six existing SWIG deprecation warnings | PASS |
| Plugin mirror parity | `tools/dev/verify_plugin_mirrors.py`; 470 pairs | PASS |
| Distribution assets | 34,529 files / 4,329,814,502 bytes | PASS |
| Cardiac Flow interchange | VM-normalization and DICOMDIR tests passed; both frozen backends contain the required modules | PASS |
| Tracked-tree secret scan | Canonical release-manager scan of the publication tree | PENDING FINAL PUBLICATION AUDIT |
| Developer Run | Owner previously confirmed the latest development state operates correctly | ACCEPTED FOR SOURCE PUBLICATION |
| Installer matrix | Six local install-QA files, sizes, hashes, and Windows versions recorded in `VERSION_3.6.7_BUILD.md` | PASS |
| Git synchronization | Canonical release-manager receipt for one exact commit across every target | PENDING PUBLICATION |
| Clean install / upgrade / uninstall / rollback | Isolated Windows host | NOT RUN |
| Real ARM64 and clinical acceptance | Representative de-identified workflows | NOT RUN |

## Deliberate exclusions

Installer binaries, temporary build workspaces, generated review images and reports,
test-control sessions, compiler crash reports, caches, bytecode, logs, credentials,
clinical data, and local machine settings are excluded from the release commit.
Generated installers remain local install-QA evidence and are not Git source assets.

## Known risks and blockers

1. Historical provider credential exposure still requires confirmed revocation,
   rotation, and repository-history remediation. A clean current-tree scan does not
   close that incident.
2. All six local installers are unsigned. Clean install, upgrade, uninstall,
   rollback, representative de-identified clinical workflow, physical printing,
   and real ARM64-host acceptance remain required before distribution.
3. The isolated Web Browser guard passes, while its Qt-global-state-sensitive file
   is not used as part of a shared-process aggregate. The documented cold-open live
   GUI gate remains pending.
4. Native Slicer metadata now reports 3.6.7, but a native rebuild and GUI acceptance
   remain separate from source publication.
5. The historical repository-wide wrapper is not release proof. Direct pytest
   selections, build fail-closed gates, and the canonical release manager are used.

## Rollback

If a post-publication defect is found, use a reviewed revert or corrective patch on
the shared branches. Never reset or force-push a shared branch, move the v3.6.7 tag,
or relabel an older artifact. Retain the local v3.6.7 installers for isolated QA but
do not distribute them until the remaining gates and explicit approval are complete.

## Approval

Source publication approved by: Repository owner request, 2026-09-21

Installer distribution approved by: NOT YET GIVEN
