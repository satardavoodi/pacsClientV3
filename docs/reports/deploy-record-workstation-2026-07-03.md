# Deployment Safety Record — AI-PACS Workstation — 2026-07-03

**Change:** Patient-load reliability refactor — canonical lifecycle model + shadow
telemetry (5 markers) + Seam A cutover (token-stale thumbnail render) + Seam B
cutover (previous-exam grow watchdog keep-alive) + retry-exhausted→FAILED tap.
All flag-gated, **default ON** for this build, each with an env kill switch.
**Gate result:** PASSED — with informed user override on the one live-unverified item.

## Files changed
- `PacsClient/utils/patient_load_lifecycle.py` (new, pure)
- `PacsClient/utils/lifecycle_shadow.py` (new, telemetry)
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_search.py` (Seam A)
- `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py` (Seam B)
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py` (Seam C tap)
- `modules/download_manager/coordinator/series_intent_coordinator.py` (+ plugin mirror) (failure tap)

## Workstation checklist
- [x] CONFIRMED — Viewer features intact — no overlay/measurement/reference-line/sync/sidebar/thumbnail feature removed; 4-patient live check (48865/49067/48981/48946) loaded thumbnails + series normally; 49067 grew to full 159 slices.
- [x] CONFIRMED — FAST mode safe — no VTK render window added; viewer edit is a log-only tap; Seam B calls a QTimer (`_ensure_dl_watchdog`), never VTK.
- [x] CONFIRMED — No cross-patient / stale mixing — Seam A keeps the existing `_is_active_patient_selection` guard before display (double-guarded); Seam B never displays; the 4-patient run showed 9,346 cross-tab drops all correctly isolated (cross-patient isolation working). Pure model touches no pixels/geometry/DICOM.
- [x] CONFIRMED — Tests + log review — `py_compile` all 6 files OK; `tests/code/ui_services` + viewer watchdog guards + download-manager retry = **359 passed / 1 skipped** (3 pre-existing failures in `test_pin_overlay`/`test_vtk_volume_service` are unrelated, confirmed via `git`); live sanam log reviewed = 0 shadow-code errors, stalls not worsened (max 4.8 s).
- [x] CONFIRMED — Rollback — three env kill switches (`AIPACS_LIFECYCLE_THUMBS` / `AIPACS_LIFECYCLE_THUMBS_ACTIVE` / `AIPACS_LIFECYCLE_GROW_ACTIVE` = `0`) revert to byte-identical legacy; plus git revert of the 6 files. **Recommendation: keep the previous installer/exe available on the other PC.**
- [x] CONFIRMED — Performance not achieved by removing function — no functionality removed; shadow adds bounded pure-python work per event (empirically no stall regression); Seam B nudge cannot raise the watchdog tick rate (fixed interval).
- [~] OVERRIDE — Clinical behavior of the CUTOVERS live-verified — the Seam A/B cutovers are behavior changes that are **safe-by-construction and unit-tested but NOT yet verified on a live source build**. Verifying them on the other PC is the explicit purpose of this build. **User made an informed decision to ship them default-on with kill switches ready.**

## Cross-project checklist
- [–] N/A — API/data boundary — no cross-system interface changed (all internal to the app).
- [–] N/A — Data ownership — the lifecycle model is in-memory telemetry; it owns/writes no clinical data.
- [x] CONFIRMED — Privacy/PHI — new logs write `patient_id` / `study_uid` (truncated) to `app.log`, which the existing pipeline already logs; **no new PHI category** (no patient names). Memory bounded (transitions cap, terminal-study eviction, throttle map cap).
- [x] CONFIRMED — Manual approval before production — the user explicitly directed shipping all changes default-on in the next build. Approval is the user's, given knowingly.

## Blocking items
None outstanding. The single live-unverified item (cutover clinical behavior) was consciously accepted by the user as the purpose of this test build, mitigated by kill switches + rollback.

## Post-deploy verification plan (on the other PC)
1. Open patients normally, including a **multi-study / previous-exam** patient on a poor-link server.
2. In `user_data\logs\app.log` confirm: `[LIFECYCLE] …->thumbs_ready`; `[LIFECYCLE-CUTOVER] rendered token-stale ACTIVE …` (Seam A firing on rapid A→B→A) and `[LIFECYCLE-CUTOVER] seam_b watchdog kept alive …` (Seam B active); rising `watchdog_grow`; previous-exam series finishing **without a second drag**.
3. Watch for any wrong-study display (should be impossible by construction). If seen → set `AIPACS_LIFECYCLE_GROW_ACTIVE=0` (and/or `AIPACS_LIFECYCLE_THUMBS_ACTIVE=0`), reinstall prior build if needed, and send the log.

## Sign-off
Manual approval given by: **vahid (user)** — directed default-on ship for the next build, 2026-07-03.
