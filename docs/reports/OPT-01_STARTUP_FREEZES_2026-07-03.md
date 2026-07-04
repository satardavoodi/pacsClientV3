# OPT-01 (startup main-thread) — mainwindow theme dedup + license-info defer — 2026-07-03

**Backlog item:** OPT-01 in `docs/OPTIMIZATION_STABILITY_RELIABILITY_MASTER_PLAN.md` §9. Third increment,
targeting the two biggest one-time startup freezes surfaced by the 2026-07-03 probe run
(`sess-2f9be9ca545a`).
**Type:** minimal safe edits, flag-gated default-on, offscreen-verified. **Live-verify pending.**

## Evidence (probe run sess-2f9be9ca545a)

Top startup stalls after the patient-search theme fix:

```
2271 ms  mainwindow_ui.apply_theme -> apply_modern_styling
1700 ms  app_handler.__init__ -> _update_license_info
1260 ms  AIPacs_ui.setupUi                      (tab construction — P1.4, still open)
```

## Fix 1 — `apply_modern_styling` idempotent dedup

`MainWindowWidget.apply_modern_styling` sets one large **top-level** stylesheet on the main window; a
top-level `setStyleSheet` cascades a full style recomputation across the entire widget tree (~2.3 s at
startup). It is called from **both** setup (`mainwindow_ui.py:679`) and `apply_theme` (`:1031`), so it
re-runs with the **same theme** during construction. The stylesheet is a pure function of the theme and
persists on the window (it also styles widgets created later), so re-applying an unchanged theme is
redundant. Guard skips it when the theme is unchanged; stores `_applied_modern_sig`. Reuses the shared
flag **`AIPACS_THEME_APPLY_DEDUP`** (same family as the patient-search dedup).

## Fix 2 — defer `_update_license_info`

`app_handler._update_license_info` (called synchronously in `__init__:434`) runs
`LicenseManager().check_license()` — which is **LOCAL** (`modules/LicenseGenerator/license_manager.py`:
hardware id via `uuid.getnode()` + SHA256, **no network**) but cost ~1.7 s on the GUI thread — and then
only sets a cosmetic "License: N days left" label. Nothing downstream depends on it running there.
Deferred to the idle event loop with `QTimer.singleShot(0, self._update_license_info)` so the login
window appears immediately; the label fills in a beat later. Flag **`AIPACS_DEFER_LICENSE_INFO`**.

## Why both are safe

- **Fix 1 is idempotent** — re-applying the identical theme produces byte-identical styling, so skipping
  is behavior-preserving; a real theme change (different dict) never matches and always re-applies; the
  window-level stylesheet covers future children, so nothing is left unstyled.
- **Fix 2 changes only *when* a cosmetic label updates**, not the license logic. `check_license` is
  local (no network hang risk) and read-only; the label is created before the deferred call runs. **No
  license enforcement / gating is touched** — this is display only.
- Both flag-gated default-on; `=0` restores byte-identical legacy. One-time startup only — no
  clinical-path or during-reading behavior changes.

## Files changed

- `PacsClient/pacs/workstation_ui/mainwindow_ui.py` — dedup guard + `_applied_modern_sig` in `apply_modern_styling`.
- `PacsClient/app_handler.py` — deferred `_update_license_info` (flag + else branch).
- `tests/code/ui_services/test_startup_freeze_defer.py` — new guard (source-pins + mirror-behavioral).

## Verification

- `py_compile` clean.
- Offscreen: **27 passed** (`test_startup_freeze_defer` + `test_theme_apply_dedup` +
  `test_status_refresh_dicom_only` + `test_status_refresh_chunked`, `-p no:debugging`).
- No existing test pins the old behavior (grep of `tests/`).

## Acceptance / rollback

- **Acceptance (live):** re-run the stall-trace probe; `apply_modern_styling` and `_update_license_info`
  should drop out of (or shrink markedly in) the startup traces; the window looks identical across
  themes; the license label still appears; theme switching still restyles.
- **Rollback:** `AIPACS_THEME_APPLY_DEDUP=0` and/or `AIPACS_DEFER_LICENSE_INFO=0` (or git revert).

## Remaining OPT-01 startup work

`AIPacs_ui.setupUi` / `add_AIPacs_tab` tab construction (~1.3 s, P1.4 / OPT-12 — defer EchoMind init
specifically, not the whole tab) and the ~0.4 s thumbnail-widget build. Same theme-dedup pattern may
apply to `data_access_panel` / `import_preview_dialog` `apply_theme` if a future trace shows them hot.
