# Deployment Safety Record — AI-PACS Workstation — 2026-06-20

**Change:** Previous Exams feature (cross-PatientID prior studies via National ID) +
follow-up fixes: exam date in study headers, blue/red origin borders (thumbnails +
viewport), single-line thumbnail border, and the multi-study **stable-slot registry**
fix for the "current drag shows previous series" bug, plus a study-scoped cache guard.

**Gate result: BLOCKED**

> The build itself will contain the fixes (they are in the source files on disk), but
> the deploy cannot be approved yet: the changes are uncommitted, the running app that
> was verified does NOT contain them, and the multi-study core change has not been
> regression-tested or run through pytest.

## Workstation checklist (AI-PACS)
- [ ] **BLOCKED — Clinical behavior preserved** — The running process that was
  verified ("seems ok now") does NOT contain the fixes: `[VIEWPORT-LOAD-TRACE]` and
  `[CACHE-STUDY-MISMATCH]` are absent from `user_data/logs/app.log` (Python source
  process started before the edits; no hot-reload). Unblock: fully stop and re-launch
  `main.py`, confirm `[VIEWPORT-LOAD-TRACE]` now appears, then re-verify 44030.
- [ ] **BLOCKED — Viewer features intact (multi-study regression)** — The stable-slot
  registry changes the core multi-study key assignment (`_rebuild_multistudy_series_index`
  + `_vc_load` fallback), affecting **all** multi-study patients, not just previous
  exams. Unblock: regression-test a same-PatientID multi-study patient (e.g. 42471
  KNEE+ANKLE per `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`) — both studies' series load,
  no flicker, correct grouping.
- [x] **CONFIRMED — FAST mode safe** — None of the edits instantiate a VTK render
  window: cache guard (dict/study compare), slot registry (list logic), viewport
  border (QFrame stylesheet), load trace (logging). Evidence: code review of the 6
  edited files. (GUI confirm still recommended.)
- [x] **CONFIRMED — Metadata & DICOM handling / isolation preserved** — Cross-patient
  isolation is unchanged or improved: the previous-exam admission is an additive
  `sanctioned_uids` allow-list; the new cache guard actively PREVENTS one study's
  pixels appearing under another. Each exam keeps its own study_uid/patient_id.
- [ ] **BLOCKED — Tests and log review** — Log review: DONE, no exceptions/tracebacks
  in app.log. Pytest: NOT run (sandbox cannot load PySide6). Unblock: on Windows run
  `python -m pytest tests/code/ui_services/test_previous_exams*.py tests/code/viewer
  -q -p no:debugging` and the multi-study/thumbnail suites.
- [ ] **BLOCKED — Rollback plan** — Previous-exams feature is flag-gated
  (`AIPACS_PREVIOUS_EXAMS=0`), but the stable-slot + cache-guard fixes are always-on,
  so rollback = git revert. The changes are **uncommitted** (4 modified files +
  `previous_exams.py` untracked), so there is no revertible commit yet. Unblock:
  `git add` (incl. the new file) + commit on `beta-version` so there is a clean
  revert point.
- [–] **N/A — Performance change doesn't disable functionality** — This is a
  correctness/feature change, not a performance optimization.

## Cross-project checklist
- [x] **CONFIRMED — API/data boundary documented** — Server contract in the attached
  `patient-past-studies-api.md`; client integration in `docs/pipelines/previous-exams.md`.
- [x] **CONFIRMED — Data ownership documented** — Each previous exam keeps its own
  study_uid + patient_id; disk keyed by study_uid; isolation guards documented.
- [x] **CONFIRMED — Privacy/PHI reviewed** — Previous exams surface the SAME real
  person's prior studies to an already-authorized operator (no new external exposure;
  not an export path). study_uids are truncated in logs. No new PHI logging.
- [ ] **NOT YET GIVEN — Manual approval before production** — The operator (vahid) is
  the approver; approval is pending this gate.

## Build-reproducibility (critical for "install on other PCs")
- [ ] **BLOCKED — Build from the verified source** — Fixes are UNCOMMITTED on
  `beta-version` and `previous_exams.py` is UNTRACKED. A build on a different PC / from
  a git checkout would ship WITHOUT them (the known stale-installer trap). Unblock:
  commit + push, build from this exact source, and let `builder/release_gate.py`
  `check_source_freshness()` pass (never `--skip-release-gate`).
- [ ] **BLOCKED — Plugin-mirror parity** — Run `tools/dev/verify_plugin_mirrors.py`
  before building (none of the touched files are believed mirrored, but confirm).

## Blocking items (what unblocks each)
1. Restart `main.py`; confirm `[VIEWPORT-LOAD-TRACE]` in app.log; re-verify 44030
   (current drag stays current; previous only on selecting/dragging a previous series).
2. Regression-test a same-PatientID multi-study patient (42471) — the stable-slot
   change touches that path.
3. Run the pytest suites on Windows (sandbox couldn't).
4. `git add` (incl. new files) + commit on `beta-version` → revertible point.
5. Build from THIS committed source; pass `release_gate.py`; run `verify_plugin_mirrors.py`.

## Sign-off
Manual approval given by: NOT YET GIVEN
