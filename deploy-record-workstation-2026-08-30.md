# Deployment Safety Record — AI-PACS Workstation — 2026-08-30

**Change:** Add EchoMind client credential hardening and prepare the v3.6.4 PyInstaller and Nuitka Windows installer processes.
**Gate result:** BLOCKED

## Confirmed evidence

- [x] Version identifiers are aligned at 3.6.4 in product source, release metadata, package
  feeds, and Windows version resources.
- [x] The v3.6.4 release tag resolves to
  `7f96b392a1cda47673f71b0c4917dedbaa74b149`.
- [x] The pre-hardening `beta-version` baseline is
  `a6ff2010e8c807ae781cb5bbe8f136ab7fc33295`; the hardening commit must be recorded as the
  installer source instead of the older published tag target.
- [x] Local remote-tracking refs for all three configured remotes pointed to the pre-hardening
  baseline when the work began.
- [x] Python 3.13.5, PyInstaller 6.11.1, Nuitka 4.1.3, Zig, Visual Studio Build Tools,
  Inno Setup, graphics DLLs, Advanced MPR payload, and disk capacity are available.
- [x] Build-environment dependency consistency passed.
- [x] Plugin mirrors passed with 458 matching pairs and zero mismatches.
- [x] Focused v3.6.4 regression coverage passed: 647 passed and 8 expected failures.
- [x] EchoMind non-live coverage passed after credential hardening: 2,315 passed, 12 skipped,
  4 expected failures, and 15 live tests deselected.
- [x] Current source and installer-payload scans found zero plaintext provider credentials and
  zero plaintext center access codes.
- [x] Center codes now open independent scrypt/AES-GCM credential envelopes, and Company Server 3
  uses the validated center credential instead of an independent embedded fallback.
- [x] A documented clean-build and artifact-verification procedure now exists in
  `docs/reports/BUILD_READINESS_PYINSTALLER_NUITKA_2026-08-30.md`.

## Blocking evidence

- [ ] Residual credential risk — client-side extraction resistance is complete for the current
  source and payload, but runtime debugging and previously published Git history remain outside
  that boundary. Dashboard quotas are the accepted enforcement layer; release-owner risk
  acceptance or provider-key rotation must be recorded before distribution.
- [ ] Clean release input — the current checkout contains eight modified tracked generated or
  machine-local files plus an untracked generated tree.
- [ ] Fresh artifacts — both staged systems and both existing installers are v3.6.3; no v3.6.4
  installer exists.
- [ ] Builder guards — the builder suite is red with seven failures: six ARM64 / Windows-on-ARM
  parity failures and one stale-stage config-parity failure.
- [ ] PyInstaller post-stage gate — `stage_config_parity` fails against the old stage.
- [ ] Reproducibility guards — dirty trees are not rejected, staged versions are not compared
  with source, Nuitka resume state is not source-fingerprinted, and cross-build coherence can
  pass when both outputs are stale.
- [ ] Source traceability — the immutable release tag predates the client-hardening commit; the
  exact hardening commit must be recorded as the artifact source and the published tag must not
  be force-moved merely to conceal that history.
- [ ] Repository-wide test evidence — the PowerShell fast-test wrapper can mask failure.
- [ ] Clinical validation — source-build clinical checks, logs, clean-machine installer QA,
  upgrade, uninstall, downgrade, and rollback have not been signed off for v3.6.4.

## Pipeline decisions

- **PyInstaller x64:** toolchain ready; release build blocked.
- **Nuitka x64:** toolchain ready; release build blocked. Plain `--resume` is prohibited for
  v3.6.4 because current checkpoints belong to v3.6.3.
- **Nuitka ARM64 / Windows on ARM:** not ready; existing architecture parity guards fail.

## Safe next action

Record the accepted client-only credential threat model and release-source decision first. Then
fix or explicitly gate the reproducibility defects, create a clean isolated checkout at the
approved SHA, rerun the builder guards, and build PyInstaller and Nuitka x64 with their full clean
procedures. Record SHA-256 hashes and complete the installer QA checklist before publication.

## Sign-off

Manual approval given by: NOT YET GIVEN
