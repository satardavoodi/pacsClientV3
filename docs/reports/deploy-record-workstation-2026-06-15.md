# Deployment Safety Record — AI-PACS Workstation — 2026-06-15

**Change:** New build on top of released **v3.2.9** (commit `28524a4`). Delta = two
defensive crash fixes from this session's other-PC log analysis, plus colour/overlay
plugin-mirror parity and tests/docs.

**Gate result:** BLOCKED — *code is verified build-ready; 2 human items outstanding
(rollback archive + your explicit go-ahead).*

## What a new build adds beyond v3.2.9 (the entire delta)
- **FIX-007** — `patient_tab_widget.py` + `service_tab_widget.py`: tab hover/active
  `QPropertyAnimation` lifetime crash (access violation on fast tab hovering). UI chrome;
  no clinical logic.
- **FIX-008** — `_hp_layout.py`: loading-overlay fade liveness guard (`shiboken6.isValid`
  + try/except → hide) so an async-open teardown race can't access-violate. UI chrome.
- **Colour/overlay mirror parity** — `builder/.../viewer/payload/.../pydicom_2d_backend.py`
  synced to the already-committed (in v3.2.9) FAST colour/overlay decode. Not a new
  feature; mirror now byte-identical to main.
- 2 new guard tests + docs (report §16–17, registry FIX-007/008, OBS-009/010).

Everything else clinical (storage consistency, colour/overlay decode, resync-on-reopen,
single-instance, cross-patient isolation) is **already inside v3.2.9** — not part of this
delta.

## Workstation checklist
- [x] CONFIRMED — Clinical behavior preserved (delta) — FIX-007/008 are UI animation
  lifetime guards; they touch no geometry, slice order, orientation, or rendering. byte-compile exit 0.
- [x] CONFIRMED — Viewer features intact — nothing removed/disabled; overlays, measurements,
  reference lines, sidebars, sync, thumbnails untouched by the delta.
- [x] CONFIRMED — FAST mode safe — delta instantiates no VTK; FIX-007/008 are home/tab UI;
  colour/overlay decode is FAST-path only (no VTK render window).
- [x] CONFIRMED — Metadata & DICOM handling preserved; no patient-data mixing — delta does
  not touch DICOM metadata or study-isolation guards.
- [~] PARTIAL — Tests & log review — targeted suites green (38: colour decode, overlay,
  storage, both crash-fix guards). A 325-test combined run showed 30 failures that are
  **test-ordering pollution** (the same files pass **19/19 in isolation**), not regressions
  and not from the delta. The build's own `release_gate.py` runs at build time. Full
  single-pass `tests/code` is suite-fragile (known) — not a code blocker.
- [ ] BLOCKED — Rollback plan exists — needs a **saved v3.2.9 installer** to reinstall from.
  Unblock: archive the current v3.2.9 installer (and/or it's recoverable via `git checkout 28524a4`).
- [x] CONFIRMED — Performance change doesn't disable functionality — delta are crash fixes,
  not perf trims; animations still play.

## Cross-project checklist
- [–] N/A — API/data boundary — delta adds no cross-system interface.
- [–] N/A — Data ownership — no data-ownership change.
- [x] CONFIRMED — Privacy/PHI — no new PHI logged/transmitted; new logging is counts/paths only.
- [ ] BLOCKED — Manual approval before production — **NOT YET GIVEN.** You asked me to
  check the code (done); you have not yet said "build and deploy." This is your call.

## Integrity checks performed
- `git status` — clean, delta known (3 source + 1 mirror + 2 tests + docs).
- byte-compile of all 3 changed source files — exit 0.
- `tools/dev/verify_plugin_mirrors.py` — **335/335 pairs match**, exit 0.
- Targeted pytest — 38 passed (FAST colour/overlay decode + storage + crash-fix guards).
- Combined-run 30 failures shown to be ordering pollution (pass 19/19 alone).

## Blocking items
1. **Rollback archive** — confirm a v3.2.9 installer (or full backup) is saved before building.
2. **Manual approval** — your explicit go-ahead to build/deploy.
3. **(Recommended, not blocking)** Commit the uncommitted FIX-007/FIX-008 + mirror sync first,
   so the build is traceable and revertible (`git revert`).

## Sign-off
Manual approval given by: **NOT YET GIVEN**
