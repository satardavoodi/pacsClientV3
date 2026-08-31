# Deployment Safety Record — AI-PACS Workstation — 2026-08-31

**Change:** Publish the latest 3.6.4 project source, regression tests, and documentation to the
three user-named GitHub repositories on `main` and `beta-version`.
**Gate result:** PASSED for source publication only. Clinical deployment and installer
distribution are not approved or performed by this record.

## Workstation checks

- [x] CONFIRMED — Product version remains 3.6.4; the existing tag will not be rewritten.
- [x] CONFIRMED — Changed boundaries were tested directly: 675 AI Imaging tests and 174 related
  viewer/import/security/build checks passed; 8 known xfails and 3 local-fixture skips are explicit.
- [x] CONFIRMED — All 458 source/plugin mirror pairs match.
- [x] CONFIRMED — All 50 staged Python files and the JSON source manifest parse; staged
  credential/identifier signatures are clear, whitespace validation passes, and `pip check` passes.
- [x] CONFIRMED — Scope and changed subsystems are documented in
  `docs/releases/VERSION_3.6.4_FOLLOWUP_2026-08-31.md`.
- [x] CONFIRMED — No viewer feature removal is part of the reviewed changes; numeric series
  handles, exact storage identity, color/cine behavior, and adjacent thumbnail contracts are guarded.
- [x] CONFIRMED — Fast Viewer and VTK remain separate domains; this publication starts neither.
- [x] CONFIRMED — Source rollback is a reviewed revert commit, never a shared-branch reset;
  experimental evidence-mode rollback is documented separately.
- [–] N/A — New GUI/clinical deployment sign-off: no running app or installed workstation is
  changed by this source push. Clinical validation remains a required later rollout gate.
- [–] N/A — Production log/installation/upgrade verification: no installer or production runtime
  is launched or deployed during this task. Automated tests are not represented as clinical QA.

## Cross-project and privacy checks

- [x] CONFIRMED — AI requests retain the existing EchoMind/GapGPT boundary; local DICOM source
  provenance and benchmark reference data are not published or included as request documents.
- [x] CONFIRMED — DICOM series identity and storage ownership are documented; the website and
  infrastructure are outside this source-publication scope.
- [x] CONFIRMED — A study-specific CLI example was replaced with a placeholder; raw patient
  data, clinical logs, runtime credentials, model outputs, and generated research are excluded.
- [x] CONFIRMED — The zero-package local generated feed is excluded; the committed 15-package
  catalog remains the publication input. Local user/build state is preserved.
- [x] CONFIRMED — User explicitly requested this source commit and push. No clinical deployment
  approval is inferred from that request.

## Sign-off

Manual source-publication approval given by: the user in the 2026-08-31 request.
Clinical deployment / installer sign-off: NOT GIVEN by this source-publication record.
