# AI-PACS Staged Audit — 2026-05-28 to 2026-05-29

Single-page index of the ten-stage audit + post-audit live fixes. Each stage produced a self-contained report. The cumulative numbers at the end show what shifted across the whole pass.

---

## How to use this document

- Each row links to the full stage report in `docs/plans/architecture/`.
- The "Outcome" column tells you whether code shipped or whether the stage was a verification pass.
- "Catalog row(s)" cross-references `docs/plans/architecture/REGRESSION_CATALOG.md` — every code change here added at least one structural guard test.
- Read top-to-bottom for the audit narrative; jump to a specific stage when investigating a related subsystem regression.

---

## The ten staged audits

| Stage | Subject | Outcome | Code changed | Guard tests added | Report |
|---|---|---|---|---|---|
| **0** | Baseline health check | HEALTHY | — | — | [`AUDIT_STAGE_0_AND_1_2026-05-28.md`](plans/architecture/AUDIT_STAGE_0_AND_1_2026-05-28.md) |
| **1** | Startup & idle stability | MOSTLY HEALTHY — found `QScrollArea.setHorizontalScrollMode` regression (deferred to Stage 9) | — | — | (same as above) |
| **2** | Patient search + patient-list workflow | MOSTLY HEALTHY — replaced 5 silent `print()` error paths with `_logger.error` | `_hp_search.py` | `test_hp_search_logging_guard.py` (5 guards) | [`AUDIT_STAGE_2_2026-05-28.md`](plans/architecture/AUDIT_STAGE_2_2026-05-28.md) |
| **3** | Patient open + right-panel thumbnails | HEALTHY — found `_hp_patient_open.py` print rebind silencing errors (deferred to Stage 10) | — | — | [`AUDIT_STAGE_3_2026-05-28.md`](plans/architecture/AUDIT_STAGE_3_2026-05-28.md) |
| **4** | Download Manager + bulk download | STRONG PASS — 35 patients enqueued in ~8 s (vs 6–30 s pre-fix). Production wire-up of `_attach_download_adapter_lazy` verified live. | — | — | [`AUDIT_STAGE_4_2026-05-28.md`](plans/architecture/AUDIT_STAGE_4_2026-05-28.md) |
| **4b** | DM controls — Pause / Cancel / Restart / Reset / Priority | STRONG PASS — priority dropdown moves rows between groups live; bulk Pause cleared 35 / 35 / 1 → 35 / 0 / 0; Retry / Cancel state machine clean | — | — | [`AUDIT_STAGE_4b_2026-05-28.md`](plans/architecture/AUDIT_STAGE_4b_2026-05-28.md) |
| **5** | Viewer (read-only) | STRONG PASS — multi-study sidebar live-verified, 11 / 11 `ViewerAdapter` guards pass | — | — | [`AUDIT_STAGE_5_2026-05-28.md`](plans/architecture/AUDIT_STAGE_5_2026-05-28.md) |
| **6** | Multi-study workflow | STRONG PASS — 239 series across 5+ studies enumerated on `malakoti somayeh`. Series-number collisions don't collapse; LSPINE-twice-in-different-studies stays separate. | — | — | [`AUDIT_STAGE_6_2026-05-28.md`](plans/architecture/AUDIT_STAGE_6_2026-05-28.md) |
| **7** | Eagle Eye / AI module | STRONG PASS — three-layer defense (structural QTimer defer guard + canonical pywinauto test + UI modality gate); zero new native faults during the session | — | — | [`AUDIT_STAGE_7_2026-05-28.md`](plans/architecture/AUDIT_STAGE_7_2026-05-28.md) |
| **8** | MPR / Printing / Education / Advanced Analysis (documentation) | STRONG PASS — per-module adapter-readiness map; refactor effort sized for Phase D.3 | — | — | [`AUDIT_STAGE_8_2026-05-28.md`](plans/architecture/AUDIT_STAGE_8_2026-05-28.md) |
| **9** | Layout & responsive UI — QScrollArea fix | STRONG PASS — `setHorizontalScrollMode` on QScrollArea was a silent no-op (method only valid on QAbstractItemView). Replaced with `horizontalScrollBar().setSingleStep(8)`. | `responsive_layout.py` | `test_responsive_layout_qscrollarea_guard.py` (4 guards) | [`AUDIT_STAGE_9_2026-05-28.md`](plans/architecture/AUDIT_STAGE_9_2026-05-28.md) |
| **10** | Logging & observability finale | STRONG PASS — 13 error-path `print()` calls in `_hp_patient_open.py` now route through `_logger.error/warning` so they reach `app.log`. The `print() → _logger.debug` rebind stays for success-trace lines. | `_hp_patient_open.py` | `test_hp_patient_open_logging_guard.py` (4 guards) | [`AUDIT_STAGE_10_2026-05-28.md`](plans/architecture/AUDIT_STAGE_10_2026-05-28.md) |

---

## Post-audit live fixes (2026-05-29)

| Subject | Outcome | Code changed | Guard tests added |
|---|---|---|---|
| **TitleBar UserInfoContainer + title_bar QFrame** vertical clamp | STRONG PASS — both QFrames had `setMinimumHeight` but no maximum + no Fixed vertical size policy → Qt's Preferred/Preferred grew them to ~170 px (pill) and ~180 px (title bar) instead of ~70 / ~84 px. Added `setMaximumHeight` + `setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)` to both. | `mainwindow_ui.py` | `test_titlebar_userinfo_clamp_guard.py` (7 guards) |

---

## Cumulative numbers (session deltas)

| Metric | Start | End | Delta |
|---|---|---|---|
| Runnable code tests (sandbox sweep) | 101 | **121** | **+20** |
| Regression catalog rows | 30 | **37** | **+7** |
| Test files total | 190 | **194** | **+4** |
| Native faults logged during session | — | **0** new | — |
| Dashboard verdict | `[1 stale warn]` | `[1 stale warn]` | unchanged (same pre-audit `native_fault.log` entry) |

The single "warn" is the 14:00 UTC `0x8001010d` entry that predates the day's first source-build launch (14:21 UTC). No new crashes were recorded during any audit interaction.

---

## Backlog carried forward (not in this session)

1. **`SARKHOSHI ABOLFAZL` body-part elision** (Stage 6 finding) — needs an `ElidedLabel` delegate on the patient-table Body Part cell.
2. **`AKRAMI FATEMEH` duplicate rows** (Stage 6 finding) — server-side data-entry concern, flag to your radiology team. NOT an AI-PACS client defect.
3. **Phase D.1** — PydanticAI parser replaces `parser_llm.py`.
4. **Phase D.2** — write-side `ViewerAdapter` (needs multi-study test suite first).
5. **Phase D.3** — per-tab module launchers for Education / Printing / Advanced Analysis (1‑line to 1–2-hour wire-ups) and MPR (4–6 h with toolbar refactor).
6. **Live pywinauto Eagle Eye drag-drop test run** on the user's Windows venv.
7. **Multi-hour `test_long_session_workload.py` run** for sub-mm/min RSS-leak detection.
8. **Crash on series drag-drop to viewport** reported 2026-05-29 by the user — investigation pending the VS Code terminal stack trace. The dropEvent already defers via `QTimer.singleShot(0)` so it's likely a VTK/render-side crash inside `change_series_on_viewer`, not the COM 0x8001010d signature. Need fresh evidence.

---

## How to add the next audit row

When the next staged audit fires:

1. Create `docs/plans/architecture/AUDIT_STAGE_N_<date>.md` from the existing template.
2. Add a row to this overview's table linking to it.
3. If the stage shipped code, add a row to `REGRESSION_CATALOG.md` and a guard test under `tests/code/system/`.
4. Update the cumulative-numbers table at the bottom.

The framework's discipline is: **every fix carries a structural guard + catalog row + documented root cause.** This overview is the master ledger.
