# Deployment Safety Record — AI-PACS Git release workflow — 2026-09-07

**Change:** Standardize versioned commit, tag, multi-remote push verification,
the Git prerequisite for full PyInstaller plus Nuitka builds, and the
repository-wide documentation route for humans and AI agents.

**Target:** AI-PACS Windows workstation source repositories and local release
build coordinator.

**Environment:** Development checkout only. No production workstation, hosted
service, installer, or customer system was changed.

**Gate result:** WORKFLOW IMPLEMENTED; CURRENT v3.6.5 PUBLICATION AND NEW FULL
BUILD BLOCKED

## Pre-deployment checklist

- [x] Scope identified: release orchestration, documentation, regression guards,
  and build handoff only.
- [x] Current branch, HEAD, configured remotes, tags, and dirty state inspected.
- [x] Exact intended target repositories and branches recorded in a reviewed
  machine-readable policy pending inclusion in the final release commit.
- [x] No force-push, wildcard push, implicit default push, automatic pull/reset,
  or installed-workstation launch path added.
- [x] Secrets are reported by path, line, and class only; values are never
  returned by the release audit.
- [x] Rollback is bounded to reverting the workflow change after it is committed.
- [ ] Current 3.6.5 source scope reviewed and frozen.
- [ ] Historical credential rotation and repository-history remediation closed.
- [ ] Private-remote authentication available for live read-back verification.
- [ ] Explicit owner authorization for an actual source publication received in
  the publication turn.

## Implemented controls

- `RELEASE.md` is the human/agent authority for version updates, release notes,
  commit format, audit, publication, recovery, and build handoff.
- `docs/release-and-build/README.md` is the navigation hub. Source-level entry
  documents route to it; it routes to `RELEASE.md`, `BUILD.md`, backend details,
  output ownership, and version evidence without duplicating the procedures.
- `docs/releases/README.md`, `tools/git/README.md`, and `tools/build/README.md`
  define the local folder responsibilities and point back to the authorities.
- `tools/git/release_targets.json` fixes the target matrix to both `main` and
  `beta-version` in `Vahid-INO/ai-pacs`, `satardavoodi/PacsClientV2`, and
  `satardavoodi/pacsClientV3`.
- `tools/git/release_manager.py` checks local release readiness, exact remote
  URLs, high-confidence tracked-tree secrets, and fast-forward safety. Live
  publication requires an explicit complete commit SHA and `--execute`, creates
  an annotated tag, uses an atomic push per remote, reads every ref back, and
  emits a receipt only after all targets match.
- The synchronization receipt is ignored build-machine state. It is bound to the
  version, tag, exact commit, target-policy hash, all branch/tag results, and a
  four-hour validity window.
- `tools/build/build_local_candidate.py` now rejects a canonical build without a
  matching fresh receipt and a clean checkout. Its explicit internal prepare-only
  lane remains available for non-promotable packaging diagnostics.
- Both release-capable backend entry points validate `build_source_manifest.json`.
  Official execution requires a receipt-bound snapshot; internal execution
  requires the explicit non-promotable snapshot and `--internal-build`. Direct
  release-capable execution from the mutable developer checkout is rejected.
- The canonical candidate coordinator forces remote application-update
  publication off. Compilation, Git source publication, and post-QA artifact
  distribution remain separate explicitly authorized operations.
- The older single-remote helper refuses live pushes to `main` and
  `beta-version`, preventing it from bypassing the release workflow.

## Verification evidence

- Focused direct pytest selection: 38 passed, exit code 0. It covers the target
  matrix, clean/dirty audit behavior, secret-value redaction, full receipt
  coverage, explicit publication confirmation, canonical documentation, and the
  release candidate packaging coordinator.
- Documentation navigation and backend-authority follow-up selection: 37 passed,
  exit code 0. It covers source-level routing, outdated active-command removal,
  official receipt/source binding, internal non-promotable snapshots, and both
  backend enforcement points.
- The combined builder plus Git guard suite passed 164 tests and retained one
  known failure against the stale generated Python
  stage's `echomind_settings.json` and `patient_table_sort.json`; generated output
  was not edited to conceal it.
- Offline audit of the actual checkout correctly reported version parity at
  3.6.5 and exact configured URLs for all three remotes.
- The final offline audit blocked publication because the checkout has 461 changed or
  untracked paths, HEAD is still the earlier 3.6.4 release commit, and the 3.6.5
  release record is not ready.
- Live unauthenticated Git inspection reached the public `pacsClientV3` remote;
  its `main` and `beta-version` refs both matched current HEAD at inspection time.
  The other two repositories require authenticated Git credentials and therefore
  are not accepted as freshly verified.
- No commit, tag, push, build, signing operation, upload, or installer execution
  was performed.

## Current blockers

1. Review the mixed 3.6.5 worktree path by path and define the exact release scope.
2. Complete credential incident response and repository-history remediation.
3. Run final subsystem, mirror, privacy, and packaging guards against the frozen
   release commit and update the release record from `BLOCKED` to `READY` only
   when the evidence supports it.
4. Authenticate both private remotes and obtain a complete online audit.
5. Obtain explicit owner authorization before running the publication command.
6. Use the resulting receipt for a fresh six-installer build and complete the
   signing, legal, isolated install/upgrade/uninstall/rollback, ARM-hardware, and
   clinical acceptance gates before distribution.

## Rollback

Before Git publication, rollback is to leave the 3.6.5 record blocked and not run
the release command. After this workflow is committed, revert it with a new
reviewed commit if it causes a regression; do not reset shared branches. The
release tool itself never rewrites published history. Existing local installers
and build evidence are unaffected.

## Sign-off

Manual source-publication approval given by: NOT YET GIVEN
Manual production-distribution approval given by: NOT YET GIVEN
