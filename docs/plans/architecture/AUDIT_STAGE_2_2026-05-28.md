# AI-PACS Application Audit — Stage 2 Report

**Date:** 2026-05-28
**Scope:** Patient search and patient-list workflow.
**Method:** Static code inspection + existing tests. The user-side live process was on monitor A but `user_data/logs/` showed no fresh writes during the audit window, so live evidence wasn't available — static evidence carried the audit.

---

## 1. What was tested

- The patient-search entry points: `perform_default_search`, `patient_list_function_identifier`, `cancel_search`.
- The server search flow: `HomeSearchService.search_server` (qasync + thread-pool delegated socket calls).
- The row-add path for socket results: `_HPSearchMixin._add_socket_patient_to_table` — the multi-study row builder.
- The default-sort and time-format normalization unit tests (`tests/code/ui_services/test_home_search_default_sort.py`).
- `print()` vs `_logger` usage across all `_hp_*.py` home-panel mixins.
- Silent `except: pass` patterns and what they're guarding.

---

## 2. Evidence collected

### 2.1 Search flow architecture (good)

The server search path is well structured:

- Cancellable via `home._cancel_search_requested` + `asyncio.CancelledError`.
- All socket I/O delegated to a `ThreadPoolExecutor` via `loop.run_in_executor`, **never on the UI thread**.
- Bulk-insert pattern with `await asyncio.sleep(0)` every `CHUNK = 10` rows. Source comment explicitly notes CHUNK=25 caused 700–950 ms freezes — historical fix, intentional.
- **Atomic swap**: old table rows only cleared when fresh results are ready (line 441), preventing blank flicker.
- Empty-result case clears the table and reports "No patients found" — no stale rows left behind.
- Post-search reporting-physician hydration runs **after** rows are inserted, in background threads with caching — does not block the UI.

### 2.2 Multi-study row builder (sound)

`_add_socket_patient_to_table` handles three independent data shapes from the server:

1. `studies` / `study_list` array — preferred, per-study data with its own `count_of_series`, `count_of_instances`, etc.
2. `latest_study_uid` scalar — fallback when only the latest is reported.
3. `study_uids` array — additional studies discovered separately.

All three feed into a dedup'd `study_rows` list keyed by study UID. **No multi-study invariants are violated**. Per-study counts are correctly preferred over patient-level fallbacks (`study.get('count_of_series') or patient.get('count_of_series')`).

### 2.3 Silent except / print() inventory

```
File                       silent except:pass   print() calls
_hp_search.py              14                   9 (5 on error paths)
_hp_download.py            4                    n/a
_hp_modules.py             13                   n/a
_hp_patient_open.py        17                   n/a
_hp_series.py              10                   n/a
```

Each silent-except in `_hp_search.py` was inspected; all are benign defensive patterns around cosmetic UI updates (right-panel `count_label.setText('Loading...')`), best-effort logging (`_log_open_trace` failure), or int() coercion fallbacks (where bad data correctly becomes 0). **No silent-except is gating critical correctness paths.**

### 2.4 `print()` error paths bypass `app.log` (real defect)

Five `print()` calls in `_hp_search.py` sat on **error paths** — exactly the kind of failure that the new catch-all `app.log` handler was designed to surface:

| Line | Path | Effect if it fires |
|---|---|---|
| 127 | `perform_default_search` outer except | Default search runs at boot; silent failure leaves a blank patient table with no diagnostic record. |
| 804 | `_add_socket_patient_to_table` outer except | A malformed patient dict drops the row silently — the canonical "missing patient" failure the user has flagged repeatedly. |
| 884 | Download-status inner except | DB lock or storage-layer issue marks every row `not_downloaded` silently. |
| 888 | Download-status outer except | Same class of issue, outer scope. |
| 1336 | Socket-thumbnail outer except | The GetStudyInfo stall regression (2026-05-27) depends on this path having a stack-trace record. |

`print()` only reaches stderr (which VS Code shows in its terminal), not `app.log`. The 2026-05-28 catch-all handler can't help. Three workflow-trace `print()`s in `cancel_search` (the `[CANCEL_SEARCH]` markers) are allow-listed — they're informational, not error-path.

---

## 3. Real issues found

### Issue #1 — Silent error paths in patient search

**Severity:** Medium. **Class:** Logging / observability. **Action:** Fixed.

**Root cause:** Five `print()` calls on error paths bypassed the project's catch-all `app.log` handler. A patient silently dropping from the list because of a malformed server payload, a default search failing at boot, or a socket-thumbnail error — all of these failures left zero record in `app.log`.

**Fix:** Replaced the five error-path `print()` calls with `_logger.error(... exc_info=True)` / `_logger.warning(... exc_info=True)` so failures now land in `app.log` with a stack trace. The three workflow-trace `[CANCEL_SEARCH]` prints were left in place by design — they're informational, not error-path.

**Safety:** Zero behavior change for the happy path. On the error path, the console handler still emits to stderr exactly as before; we only **added** a second sink (`app.log`). Cannot regress any existing functionality.

**Regression guard:** `tests/code/system/test_hp_search_logging_guard.py` — 5 structural assertions:
- `perform_default_search` must use `_logger.error`, not `print(f"Error in default search")`.
- `_add_socket_patient_to_table` must not regress to `print()` on its error path.
- Socket-thumbnail error must not use `print()`.
- Both download-status error paths must use `_logger`.
- `[CANCEL_SEARCH]` workflow markers in `cancel_search` are allow-listed.

All 5 PASS.

**Catalog row:** Added to `docs/plans/architecture/REGRESSION_CATALOG.md` as the 34th entry.

---

## 4. False positives rejected

1. **14 silent-except in `_hp_search.py`** — sampled and each is benign defensive code around cosmetic UI updates, best-effort logging, or int() coercion fallbacks. None of them is gating critical correctness paths. **No fix applied.**

2. **Default-fallback values (`'N/A'`) sprinkled through multi-study row builder** — cosmetic only. If server returns null, the user sees 'N/A' instead of empty cell. Intentional placeholder. **No fix.**

3. **`series_count` fallback to patient-level total** — defensive only. The code prefers `study.get('count_of_series')` first; only falls back to `patient.get('count_of_series')` when the study object lacks per-study data. This is consistent with multi-study invariants. **Not a bug.**

4. **`CHUNK = 10` in bulk-insert loop** — source comment explains it's a tuned value vs the previous 25 that caused 700–950 ms UI freezes. **Intentional. Don't touch.**

5. **The `app.log` mtime hasn't changed since 14:23 UTC** — sandbox/Windows mount synchronization issue, separate from search logic. Reported in Stage 0/1 as a "live evidence not available" caveat. Doesn't change anything I would fix.

---

## 5. Fixes applied

| File | Change | LOC | Risk |
|---|---|---|---|
| `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_search.py` | 5 `print(...)` error calls → `_logger.error/warning(... exc_info=True)` | +24 / -5 | Minimal — strictly additive to logging surface; no control-flow change |
| `tests/code/system/test_hp_search_logging_guard.py` | New file — 5 structural guards | +124 | None — test-only |
| `docs/plans/architecture/REGRESSION_CATALOG.md` | New row #34 | +1 | None — doc-only |

---

## 6. Tests run

After all changes:
- `tests/code/echomind/` — 72 / 0 / 0
- `tests/code/system/` (excl. `test_system_stress.py`, **including the new 5 guards**) — 34 / 0 / 0
- Subtotal: **106 passed, 0 failed** (was 101 before the new guard).

Sandbox-runnable surface remains 100% green.

---

## 7. KPI / dashboard impact

- KPI schema: unchanged. **42 keys, baseline in sync.**
- Regression catalog: **33 → 34 rows.**
- Test inventory: **190 → 191 files.**
- Dashboard verdict: `[1 warn]` — the stale pre-build native fault, unchanged.

---

## 8. Regression catalog changes

One new row, dated 2026-05-28:

> `_hp_search.py error paths (Stage 2 audit)` — Five error paths in patient search used `print()`, which only reaches stderr. The 2026-05-28 catch-all `app.log` handler exists to make these visible; `print()` defeated it. Replaced with `_logger.error` / `_logger.warning` so a per-row failure or a silently-dropped patient leaves a stack-trace record in `app.log`. Guard: `tests/code/system/test_hp_search_logging_guard.py` (5 guards).

---

## 9. Remaining risks

1. **Live evidence not collected.** The `app.log` writes from the source build were not visible in my sandbox during the audit window, so the Stage 2 findings are static-only. The fix is safe regardless (additive logging), but the next session that has live `app.log` flow should look for `Error in default search`, `Error adding Socket patient to table`, and `Socket thumbnail error` records — those previously couldn't appear and now can.

2. **The 4 silent `print()` calls remaining in `_hp_search.py`** (the `[CANCEL_SEARCH]` workflow trace + line 1442 `Error in show_patient_studies`) are **intentionally** left alone:
   - The 3 `[CANCEL_SEARCH]` lines are workflow-info, not errors.
   - Line 1442 is inside `show_patient_studies`, which is the click-to-open flow (Stage 3 territory). Will be addressed there.

3. **Other home-panel mixins** (`_hp_patient_open.py: 17 silent except`, `_hp_modules.py: 13 silent except`) carry more silent-except patterns. They map to Stages 3 / 8 respectively. Documented for future stage owners.

---

## 10. Recommended next stage

**Stage 3 — patient open and thumbnail / right-panel workflow.**

Stage 3 is where:
- The GetStudyInfo probe regression lives (`_hp_study_save.py`, regression-guarded already).
- The right-panel thumbnail load happens, where the line 1442 `print()` and the 17 silent-except in `_hp_patient_open.py` sit.
- The cross-patient thumbnail leak guard becomes relevant.

Will need fresh live `app.log` evidence to extract patient-open KPIs (`patient_open.elapsed_ms`, `patient_open.right_panel_socket_ms`). The source build must be writing to disk by then.
