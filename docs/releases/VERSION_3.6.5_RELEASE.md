# AI-PACS v3.6.5 release record

Release date: 2026-09-09
Release tag: `v3.6.5`
Source branch: `beta-version`
Source publication status: READY
Production approval: NOT YET GIVEN

## Outcome and candidate scope

Version 3.6.5 is the current development and installer target. The working
candidate includes the mammography Intelligent AI Analyze integration, current
Eagle Eye lumbar and brain work, explicit EchoMind provider selection, DICOM
compatibility changes including cardiac Flow VM normalization, viewer and import
stability work, Advanced MPR/Slicer resident-runtime work, three distribution
editions, PyInstaller/Nuitka packaging corrections, and the compatible DX wrist
analysis work from `PacsClientV2/main`.

The final source scope contains 392 reviewed source, documentation, test,
configuration-default, tooling, and packaged-mirror paths. Generated build
output, runtime state, bytecode, clinical/AI captures, credentials, caches, and
local investigation payloads are excluded. The repository owner explicitly
directed source publication after the outstanding historical-credential and
final clinical-acceptance risks were reported. This source approval does not
grant installer distribution or production acceptance.

## Version, Git, and build state

- `pyproject.toml`, `main.py`, and the Information panel currently identify
  version 3.6.5.
- The final release commit is a descendant of all six target branch tips,
  including the prior `PacsClientV2/main` Intelligent Analyze merge.
- The publication command creates the annotated `v3.6.5` tag only after the
  clean-tree, version, secret, release-record, and fast-forward audit passes.
- The reviewed source snapshot is isolated from local generated/runtime state;
  no blind whole-worktree staging is used.
- A local six-installer 3.6.5 matrix has been produced and verified as described
  in `VERSION_3.6.5_BUILD.md` and the 2026-09-06 deployment record. Those binaries
  were built before the canonical multi-remote receipt gate and are not evidence
  for a future Git-synchronized source commit.
- No source publication or installer distribution is performed by this record.

## Required publication destinations

The final release must use `RELEASE.md` and
`tools/git/release_targets.json`. One exact release commit and the annotated
`v3.6.5` tag must verify on `main` and `beta-version` in all of:

- `Vahid-INO/ai-pacs`
- `satardavoodi/PacsClientV2`
- `satardavoodi/pacsClientV3`

The resulting ignored synchronization receipt is mandatory input to the full
PyInstaller plus Nuitka coordinator in `BUILD.md`.

## Verification evidence

| Gate | Current evidence | Status |
|---|---|---|
| Version parity | Project, running application, and Information fallback read 3.6.5 | PASS |
| Canonical Git workflow guards | Focused release/build contract tests | PASS |
| Documentation navigation | Source entrypoints route through `docs/release-and-build/README.md`; focused guards pass | PASS |
| Backend build authority | PyInstaller and release-capable Nuitka stages require an approved snapshot manifest | PASS |
| Exact release diff review | 392 release-source paths in the final tree; eight generated/runtime/cache paths excluded | PASS |
| Release commit convention | Final HEAD uses the required `release(v3.6.5):` prefix | PASS |
| Multi-remote freshness | All three remotes authenticated/readable as `Vahid-INO`; final fast-forward audit follows commit | PASS PRECHECK |
| Current-tree secret scan | No high-confidence credential pattern found in the release-source tree; historical remediation remains separate | PASS CURRENT TREE |
| Developer Run | Earlier acceptance recorded; owner explicitly directed source publication after later-risk disclosure | OWNER OVERRIDE FOR SOURCE ONLY |
| Automated subsystem tests | Frozen changed-test selection: 1,315 passed, 4 deselected, exit 0 | PASS |
| Plugin mirror parity | 462 matching pairs; zero plugin-only files | PASS |
| Git synchronization receipt | Created and read back by the canonical publish command; ignored locally | PUBLICATION OUTPUT |
| Six-installer build | Existing local matrix is unsigned and predates the new receipt gate | NOT REUSABLE AS FINAL RELEASE |
| Clean install / upgrade / rollback | Isolated Windows evidence not complete | BLOCKED |

## Deliberate exclusions

The final commit must exclude generated build output, installers, local
configuration, clinical data, study identifiers, logs, credentials, caches,
downloaded model/runtime assets, recovered files, and unrelated unfinished work.
The exact exclusions must be updated after the release diff is frozen.

## Known risks and blockers

1. Revoke and rotate historically exposed provider credentials, retain runtime
   secret loading, complete repository-history remediation, and preserve the
   secret-scanning guard. Never record credential values in this document.
2. Preserve the current-tree secret scan and complete the approved history
   remediation separately; never copy generated credential state into Git.
3. Reconfirm clinical behavior and Developer Run acceptance before installer
   distribution. Source publication proceeds under the owner's explicit override.
4. Build all six installers from the exact synchronized receipt. Then complete
   signing, independent hashes, clean install, upgrade, uninstall, rollback,
   real Windows-on-ARM64 emulation, third-party legal review, and clinical
   acceptance before distribution.

## Rollback

Before publication, rollback means leaving this draft blocked and making no Git
or customer-visible change. After publication, shared branches are corrected by
a new reviewed revert/fix commit and a later patch version. The published tag is
never moved and shared branches are never reset or force-pushed.

## Approval

Source publication approved by: Repository owner, 2026-09-09
Installer distribution approved by: NOT YET GIVEN

## Immutable-tag boundary and post-tag branch follow-up

The synchronized `v3.6.5` tag resolves to commit
`0720586d61fb86fefdc59cb07f07b83dd6b92d8e` on every configured remote. It is
immutable and is not moved.

After tag publication, the development branches received a reviewed printing
follow-up that adds persisted proportional scout sizing and shared preview/export
geometry. This follow-up is intentionally not represented by the `v3.6.5` tag or
its synchronization receipt. Before building or distributing that later branch
state, assign it a new release identity and generate a new canonical receipt.
