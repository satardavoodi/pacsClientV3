# Deployment Safety Record - AI-PACS Standard Client - 2026-09-30

Change: publish reviewed v3.7.0 source and compile four Client installers.
Gate result: BLOCKED for production promotion; source publication and candidate
compilation are explicitly authorized and are not an installed deployment.

## Workstation

- CONFIRMED - Developer Client input accepted explicitly by the owner; no new
  runtime behavior is introduced by the version applicability changes.
- CONFIRMED - Automated Client/packaging checks pass: 160 initial packaging
  guards and 362 Client guards, with one already quarantined expected failure.
- CONFIRMED - Native Slicer is reused from the immutable current VC143/VMTK
  baseline; no viewer features or model fallback are removed to speed the build.
- BLOCKED - Every new frozen artifact still needs affected-workflow clean-host
  install acceptance. Source acceptance is not installed acceptance.
- BLOCKED - Actual ARM64 emulation, upgrade/uninstall and rollback evidence is
  pending; retain earlier installers and isolate acceptance from clinical work.
- CONFIRMED - Git rollback is a reviewed revert/new version, never force-push.

## Cross-project

- CONFIRMED - API/data ownership is documented in the shared pipeline and
  EchoMind server-routing documents; no website or Razi service deployment here.
- CONFIRMED - Local configs, patient data, generated probes, tokens and caches
  are excluded. Current-tree path-only scanning returns no high-confidence keys.
- BLOCKED - Historical credential rotation/history remediation remains open.
- BLOCKED - Signing, redistribution/legal review and installed clinical/PHI
  acceptance are not established by compilation.
- CONFIRMED - Owner approved publication and compilation in this chat; a
  separate manual production approval is required after installed acceptance.

## Sign-off

Source publication and compilation: explicitly approved by repository owner.
Production promotion: NOT YET GIVEN; no live host installation performed.
