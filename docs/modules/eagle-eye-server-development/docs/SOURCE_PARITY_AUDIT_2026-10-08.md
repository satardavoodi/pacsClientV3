# Local and Razi Developer source parity audit — 2026-10-08

**Result: NOT IDENTICAL. Server build readiness is blocked by unresolved source parity.**
This is a read-only source/dependency audit, not a deployment or application acceptance test.
No runtime source was merged, no service was restarted, and no build was started.

## Compared sources

- Local: `E:/ai-pacs/ai-pacs codes/ai-pacs beta version`, dirty working tree based on
  `978d81a3` (prepared 3.7.1). Both tracked and nonignored untracked files were included.
- Razi active SCM service `AIPacsEagleEye`: Running, source
  `D:/Eagle Eye Server/revisions/20261008-lumbar-marrow-r4/source`.
- The separate r3 development route is not the active shared-service source.
- The SCM source was verified before and after inventory and again after analysis.
  The private configuration and existing paired port 8002 were not changed.

## Inventory result

SHA-256 comparison of 8,024 selected local source/resource files:

| Classification | Files |
| --- | ---: |
| Exact bytes | 6,755 |
| Same after UTF-8 BOM / CRLF normalization only | 1 |
| Different content | 201 |
| Present locally, absent from active Razi revision | 1,067 |
| Razi-only files in the additional runtime scan | 0 |

The 201 content differences include **138 runtime/entry/template differences** and
63 documentation/test/build-tool differences. Of the 1,067 local-only files,
**74 are runtime files** and 993 are documentation/tests/build tooling.

| Area | Content differences | Local-only files |
| --- | ---: | ---: |
| Workstation runtime | 57 | 39 |
| Entry points and configuration templates | 4 | 0 |
| EchoMind client | 36 | 19 |
| Eagle Eye / ai_imaging | 41 | 16 |
| Documentation, tests and build tooling | 63 | 993 |

Selected missing runtime files include brain/alignment saved-results modules,
`eagle_eye_saved_results.py`, `bone_age_reference.py`, `bone_age_report.py`,
`demographics_ui.py`, `local_results.py`, `pacs_resources.py`, hosted EchoMind
attachments/correction modules and Secretary UI-observation/control modules.
Changes also exist in brain review, engine workers, server routing/demographics,
EchoMind report handling, Secretary assets/validation and lumbar marrow review.
Absence alone does not prove a module is required by the active revision; references
and workflow compatibility must be checked during reconciliation.

## Changes in both directions

112 of the differing Razi files match a known Git object at the same path; 89 do
not match the available local Git history. The latter include deployment snapshots,
uncommitted changes and documentation. They are not automatically newer or authoritative.

A three-way comparison against local HEAD classified 140 files as local equal to
HEAD / Razi different, 31 as Razi equal to HEAD / local different, 27 as both
changed and three as lacking a HEAD baseline. HEAD is not a proven shared
ancestor of these deployed snapshots. These counts MUST NOT be used as a merge
rule or evidence that Razi's version is newer. Three Python differences have the
same executable AST after docstring removal; byte parity still fails.

Razi versions of all differing files were retained in the ignored private audit
folder before any future reconciliation. Server-specific Secretary prompts and
validation, hosted report behavior, artifact publication, server request handlers
and lumbar marrow revision behavior require explicit comparison with their change
receipts. No blind local-to-Razi or Razi-to-local copy is authorized by this report.

## Dependencies and assets

Both main workstation interpreters are Python 3.13.5. Selected distributions match:
PySide6 6.10.2, VTK 9.6.1, SimpleITK 2.5.3, pydicom 2.4.5, NumPy 2.4.4,
uvicorn 0.49.0 and pywin32 311. Torch, torchvision and TotalSegmentator are absent
from both main environments; inference uses separate model environments.
This does not establish parity of those environments or their model weights.

61 selected Slicer source files match exactly. Ignored native builds, executable
payloads, model weights and distribution caches were NOT included in this source
comparison. They require their own current manifests before build approval.
The September 28 native VMTK/service cache documented by the native-baseline
runbook must not be substituted with an older cache without a new verification.
Local plugin mirror verification passed for all 517 pairs; this only proves
local source-to-mirror parity, not equality with Razi or frozen package acceptance.

## Scope and evidence limits

Host-specific configuration, credentials, certificates, patient databases,
user data, logs, generated output, virtual environments and ignored model/native
payloads were excluded. The remote extra-file scan covered the documented runtime
roots and text/code extensions; zero remote-only files is limited to that scan,
not a full forensic comparison of every file on the remote disk.

All 8,024 local files were rehashed after analysis: no changes since the initial
inventory. Razi inventory had zero read errors and checked size/mtime during each
read. These are point-in-time receipts, not a lock against future development.
This report and its documentation links were added AFTER that source snapshot.
No live GUI or model inference pass is claimed for this audit.

## Required reconciliation before build handoff

1. Use the captured path/hash inventories to reconcile the 138 runtime differences
   and 74 local-only runtime files, preserving Razi-specific changes and unrelated
   in-progress work. Review actual feature contracts, not timestamps alone.
2. Select a complete canonical candidate, synchronize packaged mirrors, run focused
   guards and verify the affected source workflows on both roles through the existing MCP.
3. Stage an immutable full Developer revision on Razi with a rollback receipt;
   retain private configuration/data and the existing paired endpoint. Activation
   must follow the documented queue-drain/service ownership procedure.
4. Rehash the complete agreed source scope in both directions after staging.
   Require zero unexplained missing/different files and a stable active source.
5. Separately verify model bundle and native Slicer/runtime manifests. Resolve the
   clean-commit/synchronization receipt and frozen Server prerequisites in BUILD.md
   and RELEASE.md before the build conversation starts a release build.

No build-ready handoff was issued. The audit does not qualify clinical behavior.

## Private receipts

Detailed inventories and differing Razi source are under
`generated-files/eagle-eye/parity-20261008/` (ignored; no patient data or live secrets).
The initial receipt hashes are:

- `local-manifest.json`: `744172c78c9c8c04bdb374e2c273011c4df14bec4303af60b73a3400dc86b185`
- `remote-manifest.json`: `9daf6fe39f2fea13c49a807e09bd9bf498af90c5263896b51c020196df038566`
- `comparison.json`: `b649767a1cf7af9d9934748c0afed493de450e6f3d7da5a918d3c6f15381c5e2`
- `three-way-analysis.json`: `8d80b59a01bdfed34143261fd6a6801f68c76c6e82f24daef139ed2da1b7d262`
- `local-stability-check.json`: `8b6eb8286d41b879d15d850805a70c60c8cfcf8b64e934ecab6a372bf2770c34`
- `dependency-inventory.json`: `d5f99756496557e6ae94ce637ba295417e05e9f267b03ca569f455f1a6088ad7`
