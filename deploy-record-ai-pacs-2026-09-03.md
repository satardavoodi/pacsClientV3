# Deployment Safety Record — AI-PACS — 2026-09-03

**Change:** Prepare version 3.6.5 Python/PyInstaller and Nuitka build candidates.
**Gate result:** BLOCKED for production; compilation has not started.

The user requested local builds, not production deployment. This record is not
release approval. The build-readiness report independently requires an isolated,
reviewed source candidate before release compilation.

## Workstation

- [ ] BLOCKED — Clinical behavior preserved — source GUI retry after the recent
  mammography correction and acceptance of the wider working candidate are absent.
- [ ] BLOCKED — Viewer features intact — automated focused coverage exists, but
  overlays, measurements, reference lines, sidebars, sync and thumbnails have not
  been accepted together for this candidate.
- [ ] BLOCKED — FAST mode safe — the version-only edit does not change rendering;
  the wider working tree changes viewer paths and requires candidate-level proof.
- [ ] BLOCKED — Metadata and DICOM handling preserved — mammography study identity
  guards pass, but broader DICOM changes and the frozen candidate remain unverified.
- [ ] BLOCKED — Tests and log review — 36 focused tests pass; builder offline suite
  is 102 passed / 7 failed / 5 deselected. Source freshness was blocked by Git
  credential interaction. No live GUI or clinical log acceptance was performed.
- [ ] BLOCKED — Rollback plan — previous 3.6.3 installers remain unchanged; a
  restorable deployment backup and upgrade/rollback rehearsal are not confirmed.
- [–] N/A — Performance change removes functionality — this turn changes version
  metadata and documentation only; wider candidate performance work is not approved.

## Cross-project

- [x] CONFIRMED — API/data boundary documented — mammography merge plan documents
  worker-side package construction and shared EchoMind provider authorization.
- [x] CONFIRMED — Data ownership documented for the mammography slice — local DICOM
  source remains viewer-owned; temporary model image packaging is worker-owned.
  No website or server write was performed by this task.
- [ ] BLOCKED — Privacy/PHI review — credential guards pass; patient data was not
  inspected or transmitted. Burned-in image identifiers, final package contents,
  and historical credential exposure require review before distribution.
- [ ] BLOCKED — Manual production approval — not requested or given; local-build
  authorization is not permission to distribute to clinical workstations.

## Build preparation evidence

- Project/application/shared builder version: 3.6.5.
- Dependency consistency: passed.
- Plugin mirrors: 462/462 matching, zero plugin-only files.
- Existing development HEAD: `4ba24be857c61a6353f705c2c2f1d7c7d5ac3df8`.
- Substantial pre-existing tracked and untracked changes preserved.
- No commit, tag, push, installer compilation, or deployment performed.
- Old installers and generated version resources were not relabeled.

## Blocking items

1. Confirm source inclusion scope for an isolated build candidate. Do not silently
   bundle all unrelated dirty-tree changes or omit new required modules.
2. Complete authenticated/noninteractive remote freshness verification.
3. Verify applicable x64 builder gates on the chosen clean source and rebuild stale
   stages. The six ARM parity failures remain a limitation of Nuitka ARM support.
4. Before distribution, complete clinical, privacy, installer and rollback QA,
   record credential-history risk handling, and obtain human production approval.

## Sign-off

Manual production approval given by: NOT YET GIVEN.
