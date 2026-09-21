# AI-PACS workstation source-publication safety record

Date: 2026-09-21
Version: 3.6.7
Change: Publish the reviewed AI-PACS workstation source commit and immutable tag to
the canonical Git remotes and branches.

Gate result: PASSED FOR SOURCE PUBLICATION ONLY

Production or installer deployment approval: NOT GIVEN

## Workstation gate

| Check | Evidence | Result |
|---|---|---|
| Clinical behavior and compatibility | Owner confirmed the latest Developer Run; changed-code and subsystem regression guards cover the reviewed source scope | PASS FOR SOURCE PUBLICATION |
| Viewer and Eagle Eye behavior | Focused viewer, Eagle Eye, Alignment, Total Spine, lumbar, mammography, brain, dataset, and workspace guards | PASS |
| FAST and stability constraints | Direct changed-code tests plus lifecycle, cache, thumbnail, download, native-fault, and Qt guards | PASS |
| Metadata and DICOM interchange | Version-parity checks plus cardiac Flow VM-normalization and DICOMDIR build inclusion | PASS |
| Build reproducibility | One content-addressed source snapshot produced the complete PyInstaller/Nuitka three-edition matrix | PASS |
| Plugin mirror parity | Canonical mirror verification | PASS |
| Installed-runtime and clinical logs | No installed executable was launched for this source push | NOT APPLICABLE TO SOURCE PUBLICATION |
| Rollback | Reviewed revert or later corrective commit; no branch reset, tag movement, or force push | READY |

## Cross-project and privacy gate

| Check | Evidence | Result |
|---|---|---|
| API and data ownership | Existing architecture and workstream-boundary documents retained | PASS |
| Sensitive data boundary | Local generated review folders, test sessions, logs, caches, crash output, credentials, and clinical data excluded | PASS |
| Current publication tree | Canonical tracked-tree secret scan required again immediately before publication | REQUIRED |
| Historical credential incident | Rotation, revocation, and history cleanup remain unresolved and separately tracked | OPEN RISK |
| Human authorization | Repository owner explicitly requested v3.6.7 commit and Git push | PASS |

## Distribution boundary

This approval covers Git source publication only. The six v3.6.7 installers remain
local install-QA artifacts. They are unsigned and have not completed clean-install,
upgrade, uninstall, rollback, real ARM64-host, representative de-identified clinical,
or final legal/distribution acceptance. They must not be publicly distributed or
promoted to production under this record.

## Sign-off

Source publication authorization: Repository owner request, 2026-09-21

Production deployment authorization: NOT GIVEN
