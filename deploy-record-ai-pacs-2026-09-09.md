# Deployment Safety Record — AI-PACS source publication — 2026-09-09

**Change:** Publish the complete reviewed AI-PACS 3.6.5 source release to every
configured Git repository.
**Gate result:** SOURCE PUBLICATION PROCEEDS BY EXPLICIT OWNER OVERRIDE;
PRODUCTION/INSTALLER DISTRIBUTION BLOCKED

## Workstation

- [ ] BLOCKED — Clinical behavior preserved — the last recorded Developer Run
  acceptance predates later 2026-09-08/09 source changes; current patient,
  viewer, printing, Eagle Eye, and EchoMind behavior has not been reconfirmed.
- [ ] BLOCKED — Viewer features intact — automated evidence exists across the
  changed domains, but final-source GUI acceptance has not been recorded.
- [x] CONFIRMED — FAST mode invariant — existing focused guards remain present;
  no release claim relies on starting an installed executable.
- [ ] BLOCKED — Metadata and DICOM handling preserved — current source includes
  DICOM and cardiac Flow compatibility work, but representative clinical
  interoperability remains a documented manual gate.
- [x] CONFIRMED — Tests and log review — the frozen changed-test selection passed
  1,315 tests with four deselected and exit code 0, including the final printing
  fidelity and transport hardening. Final installed-workstation log review remains
  part of installer acceptance.
- [x] CONFIRMED — Rollback plan — preserve the pre-release SHA; correct a
  published problem with a reviewed revert/fix commit and later patch version,
  never by moving the tag or force-pushing shared branches.
- [–] N/A — Performance change does not disable functionality — this operation
  is source publication; performance acceptance remains part of final Developer
  Run and installer QA.

## Cross-project

- [x] CONFIRMED — API/data boundary documented — EchoMind routing, DICOM export,
  build, and Git boundaries are recorded in the current subsystem and release
  documentation.
- [x] CONFIRMED — Data ownership documented — generated clinical/AI captures,
  runtime profiles, build outputs, credentials, and caches are explicitly
  excluded from release source.
- [x] CONFIRMED — Privacy/PHI reviewed for source publication — more than 31,000
  generated paths were protected by ignore rules. The staged release scope
  contains source/doc/test/mirror content only and excludes local runtime state.
- [x] CONFIRMED — Manual source-publication request — the repository owner
  explicitly requested pushing all changes on 2026-09-09. This does not waive
  credential, privacy, clinical, or remote-verification blockers.

## Git and release evidence

- [x] CONFIRMED — Branch and destinations — local `beta-version`; policy names
  `origin`, `p2`, and `satar`, with both `beta-version` and `main` required.
- [x] CONFIRMED — Current-tree high-confidence scan — no matching private-key,
  Google, OpenAI, GitHub, or AWS token pattern was found outside excluded
  generated/output/cache trees. Values were never printed.
- [ ] BLOCKED — Historical credential incident — the 2026-08-27 readiness
  report requires revocation/rotation and history remediation; completion has
  not been confirmed.
- [x] CONFIRMED — Exact release scope — 392 paths are present in the final
  release tree after the compatible `PacsClientV2/main` merge. Paths were selected through the
  source-input policy; eight generated/runtime/cache paths were excluded. No
  blind `git add -A` was used.
- [x] CONFIRMED — Release record — `docs/releases/VERSION_3.6.5_RELEASE.md`
  records source publication READY and keeps production acceptance separate.
- [x] CONFIRMED — Release commit/tag workflow — final HEAD uses the required
  release prefix and the canonical publisher creates and verifies immutable
  `v3.6.5` only after every remote branch passes the fast-forward audit.
- [x] CONFIRMED — Remote authentication — `origin`, `p2`, and `satar` are all
  readable non-interactively with the configured `Vahid-INO` credential.

## Blocking items

1. Confirm revocation/rotation of the historically exposed credentials and the
   approved repository-history remediation status.
2. Re-run and approve the current source in Developer Run after the latest
   changes, including representative clinical workflows and log review.
3. Complete signing, clean install/upgrade/rollback, installed log review, and
   explicit clinical acceptance before distributing any installer.

The repository owner instructed the agent to continue source publication after
these blockers were disclosed. The override applies only to publishing the
reviewed source commit and does not convert the remaining production items to
confirmed status.

## Sign-off

Manual source-publication request given by: Repository owner, 2026-09-09
Credential-incident closure confirmed by: NOT YET GIVEN
Final Developer Run/clinical acceptance given by: NOT YET GIVEN
Production installer-distribution approval given by: NOT YET GIVEN

## Post-tag branch synchronization

The immutable `v3.6.5` tag remains at
`0720586d61fb86fefdc59cb07f07b83dd6b92d8e`. A later reviewed source-only
follow-up adds proportional printing-scout geometry to both development branches
without moving the tag. It is covered by focused automated tests and mirror parity,
but it is not approved as a replacement 3.6.5 installer candidate.
