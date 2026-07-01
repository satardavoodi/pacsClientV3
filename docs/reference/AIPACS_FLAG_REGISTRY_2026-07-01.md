# AI-PACS `AIPACS_*` Flag Registry (2026-07-01)

Audit-only reference produced in Phase 0 of the Unified Stabilization Plan
(`docs/plans/UNIFIED_STABILIZATION_OPTIMIZATION_PLAN_2026-07-01.md`). It enumerates the
runtime environment flags, their **defaults**, and — most importantly — the **doc-vs-code
divergences** that make "the same function behave differently in different places".

This is the seed for the future central flag-registry module (Phase 4). No behavior is changed
by this document.

## Summary

- **62** distinct `AIPACS_*` env flags found in code (`main.py`, `modules/`, `PacsClient/`).
  12 default-OFF, 50 default-ON (plus non-boolean config vars).
- The **true** flag surface is larger: many default-ON "kill switches" recorded only in
  `CLAUDE.md` (e.g. `AIPACS_GROW_DISPLAYED_TO_DISK`, `AIPACS_CANONICAL_DISK_COMPLETE`,
  `AIPACS_FAST_MULTIFRAME`, the `AIPACS_MPR_*` and `AIPACS_CURVED_MPR_*` families) exist as
  temporary safety nets. Per the standing directive they should be **collapsed** after live
  verification (delete the env read + legacy branch + re-pin the guard test), one at a time.

## 🔴 Doc-vs-code divergences to reconcile (action items)

| Flag | Code default | Doc (`CLAUDE.md`) claims | Consequence | Action |
|---|---|---|---|---|
| `AIPACS_DENTAL_VTK_MPR` | **OFF** (`modules/dental_imaging/workspace.py:104`, "kept behind the flag for troubleshooting") | **ON** ("SUPERSEDES the numpy orientation as the default") | Dental Imaging ships the numpy-orientation path that `CLAUDE.md` itself calls unreliable vs standard MPR → geometry can diverge (L/R, A-P, S-I). | **Decide the intended default** (Phase 2.1). If VTK-MPR parity is the intended default, flip to `"1"` and source-build verify; else correct the `CLAUDE.md` note. Do **not** flip blind — geometry change needs clinical-lane verify. |
| Retired flags still in docs | n/a (removed in code) | referenced as active (e.g. `AIPACS_ANNOTATION_ROUTE_TO_OPEN_MPR`, `MPR_ANNOTATION_PERSIST`) | Reader confusion; false sense a path exists. | Reconcile `CLAUDE.md` (Phase 4.3). |

## Default-OFF flags (dead for end users unless an env var is set)

In the shipped GUI app the end user cannot set env vars, so a default-OFF **feature** flag is
effectively unreachable. Diagnostics being OFF is fine; **features** being OFF is the concern.

| Flag | Default | File:Line | Gates | Class |
|---|---|---|---|---|
| `AIPACS_DENTAL_VTK_MPR` | OFF | modules/dental_imaging/workspace.py:104 | VTK-standard-MPR embed for dental geometry parity | **feature ⚠ (see reconciliation)** |
| `AIPACS_DENTAL_AUTO_RECON` | OFF | modules/dental_imaging/workspace.py:176 | automatic dental reconstruction | feature |
| `AIPACS_SYNC_REPORT_STATUS` | OFF | modules/network/socket_report_status_service.py:59 | report-status sync behavior | behavior |
| `AIPACS_UNKNOWN_STALL_HOOKS` | OFF | main.py:930 | classify UNKNOWN main-thread stalls | diagnostic |
| `AIPACS_EVENT_LOOP_DIAG` | OFF | main.py:940 | Qt event-loop measurement filter | diagnostic |
| `AIPACS_MAIN_THREAD_TRACE` | OFF | main.py:1114 | stall stack capture | diagnostic |
| `AIPACS_DIAG_MODE` | OFF | main.py:1279 | real-app diagnostics recording | diagnostic |
| `AIPACS_INTENT_PRIORITY_TRACE` | OFF | .../series_intent_coordinator.py:21 | download intent priority trace | diagnostic |
| `AIPACS_LOG_SYNC` | OFF | PacsClient/utils/diagnostic_logging.py:491 | synchronous (non-async) logging | diagnostic |
| `AIPACS_NUITKA_SMOKE_TEST` | OFF | main.py:72 | staged Nuitka smoke test | build |
| `AIPACS_STAGE_SMOKE` | OFF | builder .../stage5_native_bootstrap.py:10 | Nuitka native builder smoke test | build |

Note: `AIPACS_MAIN_THREAD_TRACE` is default-OFF but stall traces **were** present in the live
logs — confirm whether the probe enables trace capture through a different path
(`AIPACS_STALL_TRACE_THRESHOLD_MS` is set to 400 ms and traces did fire), and document the actual
gate in Phase 4.

## Notable default-ON flags (kill switches — candidates to collapse after verify)

Representative set (full list lives in code; migrate to the central registry in Phase 4):
`AIPACS_MAIN_THREAD_PROBE` (stall probe, keep), `AIPACS_SWALLOW_DELETED_OBJECT_EVENTS`
(teardown-race guard, keep), `AIPACS_PREVIOUS_EXAMS`, `AIPACS_DECODE_SERVICE`,
`AIPACS_SECRETARY_WORKFLOWS`, `AIPACS_AGENT_PERMISSIONS`, `AIPACS_REPORTSTATUS_BREAKER`,
the `AIPACS_CURVED_MPR_*` family (sharpen, teardown, inherit/robust WL, xsection nav),
`AIPACS_DENTAL_ARCH_PICK` / `_ORTHO_ORIENT` / `_STACK_NAV`, `AIPACS_RULER_RENDER_ON_COMPLETE`,
`AIPACS_WEBENGINE_SHARE_GL`, `AIPACS_BROWSER_AUTOFILL`, `AIPACS_OVERLAY_CHILD_MODE` /
`_SCOPED`, plus the `CLAUDE.md`-recorded grow/multistudy/MPR kill switches.

**Collapse policy (Phase 4.1):** for each behavior flag that is default-ON and live-verified,
delete the env read + legacy branch + re-pin the guard test (the `AIPACS_DISK_COUNT_CANONICAL`
collapse is the template). Keep as flags only: genuine diagnostics, emergency kill switches for
still-unverified changes, and process/graphics/logging config.

## Tuning / config vars (not on/off) — keep

`AIPACS_STALL_THRESHOLD_MS` (100), `AIPACS_STALL_TRACE_THRESHOLD_MS` (400),
`AIPACS_STALL_TRACE_COOLDOWN_MS` (1000), `AIPACS_UNKNOWN_*_THRESHOLD_MS`,
`AIPACS_PRIORITY` (above_normal), `AIPACS_LOG_LEVEL` (INFO), `AIPACS_LOG_MAX_BYTES` (20 MB),
`AIPACS_LOG_BACKUP_COUNT` (3), `AIPACS_RESOURCE_MONITOR_INTERVAL_SEC` (2.0),
`AIPACS_DENTAL_XSECTION_*`, `AIPACS_CURVED_MPR_PROJECTION` (weighted),
`AIPACS_SYNC_VERIFY_PIXELS` (enforce), graphics/OpenGL/OSMesa paths.

> Log-hygiene follow-up (Phase 3.2): `AIPACS_LOG_MAX_BYTES` bounds a *file*, not a single record.
> The observed 13–15 MB single log line needs a per-record size cap in the formatter, independent
> of file rotation.

## Phase-1 stability flags (added 2026-07-01)

New flags introduced by the Phase-1 main-thread-blocking fixes — all default-ON with a kill switch
and a guard test (as-built: `docs/reports/PHASE1_STABILITY_ASBUILT_2026-07-01.md`).

| Flag | Default | Gates | Verify status → collapse plan |
|---|---|---|---|
| `AIPACS_THUMB_SAVE_ASYNC` | ON | thumbnail disk write on a background worker (P1.1) | LIVE-verified (pid 193028) → collapse after 1 more clean session |
| `AIPACS_STATUS_REFRESH_CHUNKED` | ON | event-loop-yielding chunking of `refresh_download_statuses` (P1.2) | offscreen only; **live path fires on Refresh click** → exercise, then collapse |
| `AIPACS_STATUS_REFRESH_CHUNK` | 2 | chunk size for the above | tuning knob (keep) |
| `AIPACS_SIDEBAR_BUILD_CHUNKED` | ON | progressive single-study thumbnail-sidebar build (P1.3) | visual-verified once (rendering) → keep kill switch through several sessions |
| `AIPACS_SIDEBAR_BUILD_CHUNK` | 3 | chunk size for the above | tuning knob (keep) |

Collapse policy reminder: delete the env read + legacy branch + re-pin the guard test **only after
solid, repeated live-verify** — matching the project's conservative kill-switch practice.
