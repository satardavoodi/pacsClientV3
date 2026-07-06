# Deployment Safety Record — AI-PACS Workstation — 2026-07-05

**Change:** Optimization/stability release — OPT-01 (GUI-thread disk-walk cache + status-refresh
trim), OPT-09 (download telemetry log-level hygiene), OPT-12 (startup single-instance sweep:
cheap-name reuse + optional ppid snapshot), the multi-study viewport study-identity gate +
per-series study_uid/series_uid stamp (clinical wrong-series fix), and the promotion (flag
removal) of 4 live-verified non-clinical optimizations to unconditional default.

**Gate result:** PASSED — cleared to publish. Post-cleanup run (~12:26) confirmed: guard tests green, app launches + runs clean, 0 crashes, 0 during-use stalls, identity gate working (6 evals), TTFI 28 ms. The only flagged item (4 new download ERRORs) is the documented PRE-EXISTING `send_request`/`get_report_status` network error in `socket_client.py` (NOT in this changeset). Clinical correctness confirmed by user; approval given.

## UPDATE 2026-07-05 (post-validation, clinical flags retired)
- **Clinical behaviour:** CONFIRMED by user ("the app is clinically correct").
- **Manual approval:** GIVEN by user ("publish it").
- **Pre-publish run (~11:57):** 0 crashes, 0 during-use main-thread stalls, identity gate 26 evals / 0 wrong-study skips, TTFI 87 ms, guard tests green. The 8 download ERRORs are PRE-EXISTING (in `socket_client.py`/`series_downloader.py`, NOT in this changeset per `git status`; identical errors recur 2026-07-04 23:42).
- **Then, per user request, the 3 CLINICAL wrong-series flags were RETIRED (made unconditional — behaviour-identical, fail-open safety adds that never block a correct render):** `AIPACS_VIEWPORT_STUDY_IDENTITY_GATE` (qt_fast_container), `AIPACS_PRIMARY_SERIES_POISON_GUARD` + `AIPACS_STAMP_SERIES_STUDY_UID` (_vc_load). Guard tests updated (flag-retired pins + kill-switch mirror tests removed). **NOT AST-verifiable in the sandbox (mount corrupting reads); must be re-confirmed by a green VS Code `pytest` + a clean app launch before building.**
- Non-clinical flags already retired earlier this session: `AIPACS_DEFER_LICENSE_INFO`, `AIPACS_THEME_APPLY_DEDUP`, `AIPACS_STATUS_REFRESH_DICOM_ONLY`, `AIPACS_STUDY_DL_CHECK_CACHE`.
- **Kept flagged on purpose (NOT validated, so NOT promoted):** `AIPACS_FAST_INSTANCE_SWEEP` + `AIPACS_STATUS_EXPENSIVE_TTL` (default-off, unvalidated) and `AIPACS_LOG_TELEMETRY_DOWNGRADE` (OPT-09, effect unconfirmed).

**Remaining before the actual build:** (1) green `pytest` on the guard suites, (2) a clean app launch (confirms the flag-collapse compiles + startup/theme/patient-list OK), (3) commit for a rollback point, (4) delete the stray `modules/EchoMind/viewer_chat/openai_reporter.py.chk.py`.

## Workstation checklist (AI-PACS)
- [ ] BLOCKED — Clinical behaviour preserved — needs the pre-publish run (`tools/dev/prepublish_check.ps1`) + your confirmation that patient open, series switching, previous-exam merge, and the correct patient/series are shown. The wrong-series identity fix was live-verified on a 2nd PC earlier, but the flag-collapse edits have not yet had a clean live run.
- [ ] BLOCKED — Viewer features intact (overlays, measurements, reference lines, sidebars, sync, thumbnails) — none of this release's changes remove or disable these; needs your visual confirmation after the run.
- [x] CONFIRMED — FAST mode safe (no VTK render window) — the only viewer-side edit is `qt_fast_container._start_qt_viewer`, which adds an EARLY-RETURN identity gate BEFORE bridge creation; it never instantiates a VTK render window. Perf/startup/logging changes don't touch rendering.
- [~] PARTIAL — Metadata & DICOM handling preserved — the perf/startup/logging changes don't touch DICOM. The identity work ADDS `study_uid`/`series_uid` onto FAST metadata (additive; improves cross-study isolation) — the 00:18 / 01:03 runs showed the cross-patient guards firing and the gate passing. Re-confirm on the pre-publish run.
- [x] CONFIRMED — Tests and log review done — pre-publish run 2026-07-05 ~11:57: STEP 1 guard suites PASS (VERDICT did not report a test failure). STEP 3 log health: **0 crash/fatal markers, 0 during-use main-thread stalls, identity gate 26 evals / 0 wrong-study skips, TTFI healthy (87 ms)**. The 8 "new download ERROR" records are PRE-EXISTING and NOT introduced by this release: `git status` confirms `socket_client.py` / `series_downloader.py` are NOT in the changeset, and the identical `send_request` / `get_report_status` errors recur on 2026-07-04 23:42 (known non-blocking GetReportStatus/socket network errors; report column only, no image-data impact).
- [ ] BLOCKED — Rollback plan exists — the flag collapses DELETED the legacy branches, so revert = git revert / restore to the prior commit. Needs your confirmation the tree is committed and revertible. **(question below)**
- [x] CONFIRMED — Performance change doesn't disable functionality — the perf items are caches / dedup / defer that preserve behaviour; the collapses removed only the flag wrapper, keeping the already-default optimized path. Guard tests assert behaviour parity.

## Cross-project checklist
- [–] N/A — API/data boundary documented — no external API or data-boundary change this release (all changes internal to the workstation).
- [–] N/A — Data ownership documented — no change to which system writes which data.
- [x] CONFIRMED — Privacy/PHI reviewed — no NEW PHI exposure: OPT-09 only changes log LEVEL (WARNING→INFO) not content; the identity gate logs study/series UIDs that the app already logs elsewhere; the status cache logs nothing new. No PHI added to logs/transmission/cache vs. the prior build.
- [ ] BLOCKED — Manual approval before production — your explicit go-ahead after a clean pre-publish run. Never granted by the model. **(sign-off below)**

## Blocking items (remaining after the 2026-07-05 pre-publish run)
1. Clinical behaviour + viewer features — your visual confirmation from the run: patient/series nav, overlays, measurements, thumbnails, and the CORRECT patient/series shown.
2. Rollback path — confirm the change is committed (or backed up) and you can revert to the prior version.
3. Manual approval — your explicit sign-off after 1–2.

## Notes / non-blocking follow-ups
- **OPT-09 downgrade unconfirmed:** `download_diagnostics.log` WARNING total still grew (37,949; 0 INFO seen on a stale-mount read), so the telemetry WARNING→INFO relabel may not be taking effect. This is LOG HYGIENE only — no clinical/stability impact — so it does NOT block the release. Verify separately (a run with downloads, then check for `| INFO ` telemetry lines); if absent, debug `TelemetryLevelDowngradeFilter` wiring under the async QueueListener. Kill switch already exists.
- **Changeset also contains `build_nuitka.py`** (from the earlier Nuitka build work) — confirm that is intended for this publish.
- **Stray file `modules/EchoMind/viewer_chat/openai_reporter.py.chk.py`** (untracked `.chk.py` backup) — should NOT ship; remove or gitignore before packaging.

## Sign-off
Manual approval given by: **vahid** ("publish it") — clinical correctness confirmed.
Conditional on the post-cleanup checks passing: green `pytest` guard suites + a clean app launch after the clinical-flag removal.
