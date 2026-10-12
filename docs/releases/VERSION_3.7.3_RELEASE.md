# AI-PACS v3.7.3 Standard Client candidate

Release date: 2026-10-12
Release commit: resolve from the annotated tag and exact Git synchronization receipt
Release tag: `v3.7.3`
Source branch: `beta-version`
Source publication status: READY
Production approval: NOT YET GIVEN

## Outcome and scope

The owner requests latest Windows Standard Client source publication to all three
repositories and four installers: Standard and ARM64-emulated for PyInstaller
and Nuitka. The owner explicitly directed taking the current Client snapshot
without inter-thread coordination, stating that no shared changes are pending.
This records the Client input-selection direction, not verified Razi parity or
permission to deploy shared Server changes. No Server installer is selected.

Include current Education/media, Home/catalog/thumbnail, Fast Viewer lifecycle,
startup/shutdown, Settings, EchoMind/Secretary integration and Advanced Viewer
Python presentation. Shared Server source remains source only. This packaging
task implements no runtime bug fix. Existing runtime and regression changes
retain their subsystem owners and evidence; compilation is not clinical proof.

## Build contract

Follow RELEASE.md, then BUILD.md and tools/build/build_local_candidate.py with
the fresh exact-commit Git receipt and --target client. Both backends consume one
sanitized immutable snapshot. Reuse the verified native cache:
generated-files/distribution-assets-native-vc143-vmtk-service-20260928.
Current Python/UI overlays, including viewer_chrome.py, come from the snapshot;
do not rebuild Slicer or reuse a previous-version application core.

Final deliverables remain exclusively in the existing folders:

- builder/output/installer/ai-pacs standard v3.7.3.exe
- builder/output/installer/ai-pacs arm64-emulated v3.7.3.exe
- builder nuitka/output/installer/ai-pacs standard v3.7.3.exe
- builder nuitka/output/installer/ai-pacs arm64-emulated v3.7.3.exe

ARM64-emulated means x64-on-Windows-ARM64, not a native ARM64 binary. Compile
backends sequentially; preserve previous artifacts, caches and build receipts.

## Compatibility, migration and stored data

Retain DICOM EOF recovery, cardiac Flow VM normalization, codecs, DICOMDIR/Lite
Viewer, Qt/ICU hygiene, customized Slicer hidden startup and lumen workspaces.
Ordinary Eagle HTTP password login is separate from mobile-to-Workstation Agent
QR/HTTPS pairing; the October 12 architecture boundary remains authoritative.
Host credentials, licenses, databases, patient data and machine configuration
are not release inputs. Sanitize candidate configuration only. No clinical data
migration, installed executable launch or Razi service transition is authorized.

## Verification evidence

| Gate | Evidence | Result |
|---|---|---|
| Owner selection | Explicit independent Client snapshot and four-output request | Accepted for source freeze and compilation only |
| Version parity | Project, main, Information fallback and legal applicability | Updated to 3.7.3; post-edit packaging/version selection passed |
| Focused packaging/DICOM guards | Direct pytest, --reruns 0, exit 0 before version update | 177 passed; six dependency deprecation warnings |
| Plugin mirror parity | verify_plugin_mirrors.py, exit 0 | 531 matching pairs, zero plugin-only |
| Build environment | .venv_build python -m pip check, exit 0 | No broken requirements |
| Native assets | prepare_distribution_assets.py --check --profile client, exit 0 | 34,469 files / 4,356,143,152 bytes verified |
| Current Client regression guards | Direct pytest, no reruns; separate selections overlap | 127 passed / 1 opt-in DLL probe skipped; 148 post-version packaging/Education/Settings passed; expanded 185 passed / 1 inconsistent fixture failed, then 63 focused and 187 full expanded tests passed after test-only correction, all final exits 0 |
| Source privacy and secret signatures | Deliberate path inventory, AST parsing, path-only release scanner | 921 selected source files, 708 Python files parsed, zero high-confidence signatures; eight verified private backups; no source drift at review; historical remediation separate |
| Git synchronization | Initial push rejected for oversized documentation; owner-authorized local recovery, then canonical online publication | Fresh exact-commit receipt pending; no published ref is rewritten |
| Documentation recovery | Two regression guards reproduced failure before repair; original/proposal SHA-256 and per-run round-trip proof retained privately | Both guards and 68 adjacent release/version guards passed after recovery, direct exit 0; no tracked working-tree file exceeds 95 MiB |
| Immutable input | build_source_manifest.json | Pending |
| Four artifacts | Backend exits, coherence, contents, independent hashes and versions | Pending |
| Developer parity / actual Server acceptance | Current readiness receipts | Not established by this Client packaging task |
| Installed acceptance | Exact candidate on WinA100; upgrade/uninstall/rollback and real ARM64 | Pending |

## Deliberate exclusions

Exclude machine-local settings, runtime profiles, operational receipts containing
private context, logs, databases, clinical inputs, credentials, generated probes,
compiler outputs and later changes after the freeze. Preserve them locally.
No Server builds, standalone AI model bundles, Razi activation or customer
deployment are included. Do not stage the dirty checkout indiscriminately.

## Known risks and blockers

The first unpublished v3.7.3 commit, 8657829b55177e724d4887681c8fdffb3719d1fe,
contains an already-corrupted regression catalog whose repeated legacy encoding
expanded it to 132,698,029 working-tree bytes. GitHub rejects the 126.55 MiB Git
blob. Both canonical publication attempts stopped at the first remote; fresh
readback confirmed all three repositories retained v3.7.1 on both branches and no
v3.7.3 tag. No build had started and no synchronization receipt was created.

A private, exact-hash original backup and a recovery proposal are retained under
generated-files/release-local-settings/v3.7.3-20261012. The proposal is 618,173
bytes: 361 long non-ASCII runs were reversed through strict, individually
round-tripped encoding transformations. ASCII narrative and structure are
unchanged. On 2026-10-12 the owner explicitly approved applying the verified
recovery and replacing only the unpublished local commit/tag, followed by push
and Client compilation. Rechecked all destinations before this operation: no
remote v3.7.3 existed. Preserve the failed commit and tag object in local recovery
refs; amend only this unpublished commit and let the canonical publisher recreate
the local tag. Never force-push or rewrite any published history. All eight
private host settings were restored exactly after publication failed; their
verified backups/stash remain and are preserved again for clean snapshot capture.

The expanded Client verification found one new test fixture expecting raw list
reversal to change displayed card order. The runtime file is unchanged from the
published HEAD and already applies canonical series sorting. Correct the fixture
to change actual sort keys and add the complementary retained-order/action test;
63 focused guards then passed. No viewer behavior was changed or guard removed.
The opt-in synthetic Windows detach-DLL probe was skipped, not counted as passed.

Source inventory includes the imported CRM reference code/catalogs and migration
hashes, not private host databases or reception sessions. Their presence is not
CRM/Server installed qualification or approval to activate those integrations.

The October 12 shared-AI readiness report remains blocked: full Developer parity,
activated-source GUI/upstream acceptance and a personal-completion prompt
attestation gap require their owning workstream. The owner-directed Client freeze
does not mark them passed. Historical credential rotation/history remediation,
legal review, signing and clean-host clinical/install qualification remain open.
Source publication and compiling candidates do not authorize production rollout.

## Rollback

Keep the complete 3.7.1 receipt-backed and 3.7.2 local-QA matrices, their hashes,
native caches and source manifests. Before installed QA, retain the prior
installer and a host-specific configuration/data backup. Use an isolated test
host; never downgrade clinical databases speculatively. Shared Git rollback uses
a reviewed revert/new patch release, never force pushes or moved published tags.

## Approval

Source publication approved by: repository owner, request for v3.7.3 to all Git repositories.
Client compilation approved by: repository owner, independent current-source freeze.
Installer distribution / production approval: NOT YET GIVEN.

See deploy-record-client-2026-10-12.md for the separate production safety gate.
Update evidence from actual command exits and immutable receipts; pending is not
a pass. Post-freeze documentation receipts do not modify captured compiler input.
