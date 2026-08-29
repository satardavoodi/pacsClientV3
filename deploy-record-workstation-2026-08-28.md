# Deployment Safety Record — AI-PACS Workstation — 2026-08-28

**Change:** Evaluate publishing the current Eagle Eye lumbar/LLM, overlay reentrancy, and EchoMind pipeline changes and producing a new Windows installer.
**Gate result:** BLOCKED

## Repository and release evidence

- [x] CONFIRMED — Release branch freshness — local `beta-version` commit `5deb8ee731ed` matches the current remote `origin/beta-version` tip.
- [ ] BLOCKED — Reproducible release commit — the pre-audit working tree contained 32 tracked modifications and 46 untracked paths, with no staged changes; this safety record adds one more untracked file. The new Eagle Eye package is untracked and therefore can enter a local build without being recoverable from Git.
- [ ] BLOCKED — Release scope — product source and tests are mixed with tracked generated Nuitka state, local runtime/profile state, patient-table UI state, provider probe output, and one-off analysis scripts.
- [ ] BLOCKED — Version and release record — the source version remains `3.6.3`, so a new release version and matching release notes have not been approved or committed.
- [x] CONFIRMED — Plugin mirror parity — `tools/dev/verify_plugin_mirrors.py` reports 456 matching pairs and zero mismatches.
- [x] CONFIRMED — Build prerequisites — Python 3.13.5, dependency consistency, Inno Setup, software OpenGL DLLs, OpenCV, and Printing source/plugin imports were verified.
- [x] CONFIRMED — Focused regression suite — 313 tests passed with three deprecation warnings using direct pytest.
- [ ] BLOCKED — Repository-wide regression gate — the 2026-08-27 direct fast lane is red, and `run_test.ps1 -Fast` still masks failures because `$Fast` and `$fast` collide in case-insensitive PowerShell.
- [ ] BLOCKED — Credential incident — API-key-shaped strings remain committed in EchoMind source, packaged mirrors, tests, and documentation; revocation/rotation, runtime secret loading, history cleanup, and automated scanning are incomplete.
- [ ] BLOCKED — Current staged artifact — the post-stage release gate fails `stage_config_parity` for `patient_table_sort.json`; the existing v3.6.3 stage and installer must not be reused for this release.
- [ ] BLOCKED — Clean release artifact — no clean PyInstaller release build has been run from a clean, committed release SHA.
- [ ] BLOCKED — CI and review enforcement — no GitHub Actions workflow currently enforces secret scanning, tests, lint, or package parity before merge.

## Workstation checklist

- [ ] BLOCKED — Clinical behavior preserved — focused automated tests passed, but patient workflow, study/series navigation, and clinical tools have not been live-verified in the source build for this release candidate.
- [ ] BLOCKED — Viewer features intact — overlays are covered by focused guards, but measurements, reference lines, sidebars, synchronization, and thumbnails have not been manually verified together.
- [ ] BLOCKED — FAST mode safe — the change touches FAST/viewer integration; no release-candidate proof yet confirms that FAST mode avoids VTK render-window construction across the affected paths.
- [ ] BLOCKED — Metadata and DICOM handling preserved — the new Eagle Eye workflow handles clinical images/evidence, but release-candidate validation has not confirmed identity isolation, ordering, metadata preservation, and absence of stale cross-study results.
- [ ] BLOCKED — Tests and log review — the focused suite passed, but the repository-wide suite is red and no source-app log review has been completed for the release candidate.
- [ ] BLOCKED — Rollback plan exists — v3.6.3 remains the prior tagged release, but the new release has no committed SHA, versioned artifact, tested uninstall/downgrade path, or written rollback trigger.
- [ ] BLOCKED — Performance change does not disable functionality — no live workflow or performance bake has confirmed that the current changes preserve all clinical functions under realistic use.

## Cross-project checklist

- [ ] BLOCKED — API/data boundary documented — the exact image, metadata, prompt, report, and evidence fields sent by the new Eagle Eye/LLM workflow require a final release-scope review.
- [ ] BLOCKED — Data ownership documented — ownership and retention for local analysis/session stores and provider responses require explicit confirmation for the release candidate.
- [ ] BLOCKED — Privacy/PHI reviewed — generated provider-response files and one-off clinical analysis tools are present in the untracked scope, and the committed credential incident remains unresolved.
- [ ] BLOCKED — Manual approval point before production — the repository owner has not yet approved a final commit, release version, installer artifact, or production promotion.

## Blocking items

1. Define and review the exact release file set; exclude generated, machine-local, probe, and patient-specific artifacts unless explicitly approved.
2. Resolve the committed credential incident and add an automated secret-scanning guard.
3. Fix the masked test-wrapper exit code and restore a trustworthy direct repository-wide baseline.
4. Commit the approved scope with a new version and release notes, push normally to the intended remote branch, and prove the remote SHA matches the local release SHA.
5. Run a clean PyInstaller build with all release gates enabled; do not reuse the current v3.6.3 stage or use `--skip-pyinstaller` / `--skip-release-gate`.
6. Complete source-build clinical validation, log review, clean-machine installer QA, artifact hashing, and rollback verification.
7. Obtain explicit human approval before publishing the tag, installer, update feed, or production release.

## Sign-off

Manual approval given by: NOT YET GIVEN
