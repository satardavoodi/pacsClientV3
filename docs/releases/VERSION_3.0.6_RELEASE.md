# AIPacs v3.0.6 Release Notes

**Release date:** 2026-05-18  
**Branch:** beta-version  
**Previous stable:** v3.0.5

---

## Summary

v3.0.6 is a rollup release for the current optimization cycle and repository hygiene work:

- DB optimization updates
- UI/UI responsiveness updates
- Data-flow and coordination hardening
- Documentation and test-file organization cleanup

This release also aligns stable-version metadata across runtime and documentation.

---

## Version Alignment

The following canonical version markers are set to `3.0.6`:

- `pyproject.toml` -> `version = "3.0.6"`
- `main.py` -> `app.setApplicationVersion("3.0.6")`
- `docs/README.md` -> current stable `v3.0.6`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.0.6`
- `.github/copilot-instructions.md` -> current stable `v3.0.6`

---

## Repository Organization (Docs/Tests)

Included cleanup and organization updates:

- Root-level forensic/investigation documents moved under:
  - `docs/archive/root-investigations/2026-05-stack-order/`
- Root-level ad-hoc test scripts moved under:
  - `tests/manual_archive/root_ad_hoc/`
- Added archive index pages:
  - `docs/archive/root-investigations/README.md`
  - `docs/archive/root-investigations/2026-05-stack-order/README.md`
  - `tests/manual_archive/README.md`
- Removed stale generated text artifacts from repository root.

---

## Notes

This release note is intentionally concise and release-oriented. Detailed technical evidence remains in subsystem docs and test artifacts already present in the repository.
