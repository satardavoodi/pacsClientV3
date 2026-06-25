# AIPacs v3.3.7 Release Notes

**Release date:** 2026-06-26
**Branch:** beta-version
**Previous stable:** v3.3.6

---

## Summary

v3.3.7 advances the stable version line and publishes the full current
beta-version source state to all configured remotes. It introduces a professional
Dental Imaging workspace, a substantial Dental Curve MPR quality and stability
pass, viewer pipeline unification groundwork (shared series-display state authority
and stable viewer identity), download resilience on poor networks, and EchoMind
agent-control (permissions + multi-step workflows).

---

## Version Alignment

The following canonical version markers are set to `3.3.7`:

- `pyproject.toml` -> `version = "3.3.7"`
- `main.py` -> `app.setApplicationVersion("3.3.7")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.3.7`
- `docs/README.md` -> current stable `v3.3.7`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.3.7`
- `.github/copilot-instructions.md` -> current stable `v3.3.7`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.3.7`

LICENSE unchanged.

---

## Included In This Release

- Dental Imaging professional module (CBCT workspace) and improved Dental Curve MPR
  (sharper panoramic, robust windowing, 2D mouse/Window-Level, VTK point-picking,
  in-place viewport, teardown/close crash fixes)
- Viewer pipeline unification groundwork: shared series-display state authority and
  stable viewer identity
- Poor-network progressive-load KPIs, reception-API circuit breaker, disk-resume
  without re-downloading, resume-livelock fix on multi-study patients
- Real-time multi-study thumbnail status, history series sorted first, pin overlay,
  patient-tab local reminder
- EchoMind agent-control: permission gate and multi-step workflow engine
- Ruler renders on completion; deleted-object teardown crash guard
- Stable version bump to v3.3.7 across canonical metadata files

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.3.7` across canonical metadata files
- Force-pushed to main + beta-version on all configured remotes (ai-pacs, PacsClientV2, pacsClientV3)
