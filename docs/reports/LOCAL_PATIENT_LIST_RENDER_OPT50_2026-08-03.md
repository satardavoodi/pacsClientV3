# OPT-50 — Local patient list: why it dies past ~2000 studies

**Date:** 2026-08-03 · **Status:** shipped default-on, six kill switches, needs live verify
**Master plan:** §9 OPT-50, §15 2026-08-03 · **Memory:** `local_list_render_opt50_2026-08-03.md`

---

## 1. The report

> "The Local patient list is still too slow, especially above ~2000 studies. Loading, filters,
> search, sorting by Imported Date, re-rendering — the UI freezes or lags. The user normally only
> needs the first 50 results immediately."

OPT-43 (2026-07-24) already made the list *paint* early: 20 rows up front, the rest streamed on an
idle timer. That fixed **time to first pixel** and nothing else. Every per-row cost was still paid,
just moved behind the first paint — so the list looked fast for a moment and then fought the user
for the next 40 seconds.

---

## 2. Method

Nothing here was guessed. A new standalone benchmark builds a **real** `PatientTableWidget`
offscreen, feeds it N synthetic studies through the real `load_progressive` path, and counts the
things that were suspected:

```
.venv\Scripts\python.exe tests\bench\bench_local_patient_list.py --rows 2000            # current
.venv\Scripts\python.exe tests\bench\bench_local_patient_list.py --rows 2000 --legacy   # pre-OPT-50
```

`--legacy` sets every OPT-50 kill switch to 0, so both arms run on the same machine, same data,
same build. cProfile over the same harness supplied the per-function split.

The bench isolates its settings directory (copying the user's real `patient_table_sort.json` in
first), so a run measures the user's actual sort configuration without rewriting it.

---

## 3. What was actually wrong

### 3.1 The per-study dedup scan — O(N²)

`add_patient_data` protects against duplicate rows by scanning for the incoming `study_uid`:

```python
for _row in range(self.results_table.rowCount()):
    _uid_item = self.results_table.item(_row, COL['study_uid'])
    if _uid_item and _uid_item.text().strip() == incoming_study_uid:
```

Every row scans every row already inserted. At 2000 rows that is **1 999 000** `item()` + `.text()`
round-trips through the Qt binding — and the answer is "not present" essentially every time.

This is the single reason the list is fine at 200 studies and unusable at 2000: the cost is
quadratic, so a 10× bigger database is 100× more work.

### 3.2 Two SQLite connections per row

- `check_patient_visited(patient_id)` → `find_patient_pk` → `get_db_connection()` + a `SELECT`.
- `_resolve_imported_on(uids)` memoises per search, but a freshly-searched study is **always** a
  miss, so it called `get_imported_at_map([one_uid])` — another connection, another `SELECT`.

**4000 fresh SQLite connections** for a 2000-study list, all on the GUI thread.

### 3.3 Three whole-table passes after every 40-row batch

`_progressive_render_next` brackets each batch in `begin_bulk_insert()`/`end_bulk_insert()`, and
`end_bulk_insert` calls `_finalize_bulk_insert_ui()`. That ran, **~50 times per load**:

| pass | cost per call at N=2000 |
|---|---|
| `refresh_table_anti_aliasing` → `apply_anti_aliasing_to_table` | N × C `item.setFont()`, each emitting a model `dataChanged` — ~30 000 signals |
| `_programmatic_sort` | a full `sortItems` **plus** a restore pass calling `_extract_row_data(row)` (~30 `item()` lookups) on every row — ~60 000 lookups |
| `_update_results_count` | an O(N) modality summary, immediately overwritten by the progressive label |

Total across a load: **832 000** anti-alias cells and ~3 M sort-restore lookups.

### 3.4 The Assign/Report columns — half the whole render

cProfile at 800 rows, before any fix:

```
6.807 s   ino_assignment_server_state.get_state   (2400 calls)
1.278 s   ino_assignment_history.read_all         (2400 calls)
0.849 s   report_status_for_reception             ( 800 calls)
```

against a total `add_patient_data` of 13.2 s. Three calls per row, because
`_assign_icon_state` and `_apply_report_status_display` each go through `assignment_display_for`,
and `get_assignment_details` goes again — and **each call re-opened and re-parsed the whole JSON
store from disk**. `report_status_for_reception` is itself a full table scan, called once per row —
another quadratic term.

This is the same defect class as the Status column fixed on 2026-08-02: per-row disk I/O on the GUI
thread, in a column nobody thought of as expensive.

### 3.5 Per-row filesystem calls in `render_one`

`Path(study_path).exists()`, `has_subfolders()` (an `opendir`), and sometimes a thumbnail directory
scan — 1–3 blocking syscalls per row, interleaved with widget construction on the GUI thread.

### 3.6 The bonus bug: streamed rows were never sorted

```python
if getattr(self, '_active_sort_col', None) is None:
    self._programmatic_sort(COL['date'], Qt.DescendingOrder)
```

The per-batch sort ran **only when no user sort was active**. The user's saved config has
`active_sort_col = 15`. So every row the background streamer appended landed at the bottom,
unsorted, and stayed there until the header was clicked again — "sort by Imported Date" was
silently covering only the first 20 rows on a large list.

### 3.7 The data layer

`search_patients_local` returns `SELECT p.*, s.*` with no `LIMIT`, ordered by
`p.patient_name, s.study_date DESC` — an ordering that `home_search_service` then throws away by
re-sorting in Python and reversing. And **no index existed** on `studies.patient_fk` (the LEFT JOIN
key), `study_date`, `imported_at`, `modality`, or `patients.patient_name`.

---

## 4. What was changed

Six independent kill switches, all default-ON; setting any to `0` restores exactly that piece's
previous behaviour.

| # | Flag | Change |
|---|---|---|
| 1 | `AIPACS_LIST_UID_INDEX` | A `study_uid` presence **set**. The row scan runs only when the set says the uid might be there. Safe by asymmetry: a *False* is authoritative (never inserted ⇒ the scan would have found nothing), a *True* only means "go scan" — so a stale set can never create a duplicate row, only cost one redundant scan. Rebuilt (not emptied) in both `clear_table` paths, because a clear **keeps pinned rows**. |
| 2 | `AIPACS_LIST_DB_PREFETCH` | New `dicom_db.get_existing_patient_ids()` (chunked at 500 to stay under SQLite's variable limit) plus the existing `get_imported_at_map`, both run **once on the worker** in `search_local`; `prime_visited_patient_ids` / `prime_imported_on_cache` seed the widget before rendering. Misses are primed as `""` so a study with no stamp does not re-query. Un-primed callers (single-row refresh, server path, tests) keep the original per-row lookup. |
| 3 | `AIPACS_LIST_BATCH_FINALIZE` | While a stream is in flight: anti-alias only the **new row range** (new `font_manager.apply_anti_aliasing_to_rows`; a refresh that does not grow the table still gets the full pass, so no row is left unstyled), skip the count, and debounce the sort into **one** `_on_stream_settled` pass 140 ms after the last batch — which sorts by the **active** column, fixing §3.6. |
| 4 | `AIPACS_INO_STORE_CACHE` | mtime + size guarded read caches in `ino_assignment_server_state._load`, `ino_assignment_history.read_all` and `ino_assignment._config`. Explicit invalidation on write (in `_save`'s `finally`, because `set_state` mutates the dict `_load` handed it — a *failed* save must not leave that visible), and copies handed out so no caller can poison the cache. Side benefit: far fewer open handles on `server_state.json`, which is exactly what its `os.replace` fights with on Windows. |
| 5 | `AIPACS_LIST_REPORT_MEMO` | `report_status_for_reception` answered from a memo armed for the render pass only (`load_progressive` → `_on_stream_settled` / `clear_table`). It reproduces the scan exactly: `add_patient_data` records each patient with `setdefault`, so the **first** row of a patient wins — which is what the scan returned; an empty scan is **never** cached (that would poison the patient's very first row, which asks before its own row exists); a miss still scans. Outside a render pass the memo does not exist and every call is live. |
| 6 | `AIPACS_LIST_PATHS_OFFTHREAD` | The disk resolution lifted **verbatim** out of `render_one` into module-level `_resolve_renderable_study_path`, run on the worker: the first `_PATHS_HEAD=60` rows before the first paint (milliseconds), the tail in the background while the streamer renders. `render_one` falls back to resolving inline for any row the worker has not reached — the optimisation is never a precondition, so the race is harmless by construction. |

Plus, outside the flags:

- Five `CREATE INDEX IF NOT EXISTS` on `studies(patient_fk / study_date / imported_at / modality)`
  and `patients(patient_name)`. Read-path only; no column, table or row semantics change.
- `_programmatic_sort` now reads one field per row via the new `_row_study_uid` instead of building
  a ~30-lookup dict per row — this also speeds up **every user-initiated column sort**, which was
  one of the original complaints.
- `_assign_icon_state` resolves `report_status_for_reception` once instead of twice.

---

## 5. Results

Benchmark, 2000 synthetic studies, same machine, same run conditions:

| metric | legacy | OPT-50 | |
|---|---:|---:|---|
| full load | 42 723 ms | **13 866 ms** | 3.1× |
| worst single GUI-thread block | 1 139 ms | **271 ms** | 4.2× |
| first paint | 285 ms | **114 ms** | 2.5× |
| SQLite round-trips | 4 000 | **1** | |
| dedup-scan rows visited | 1 999 000 | **0** | |
| anti-alias cells restyled | 832 000 | **32 000** | 26× |
| whole-table sorts during load | 0 *(the bug)* | **1** *(correct)* | |

Verification: 46 new guard tests (`tests/code/ui_services/test_local_list_render_opt50.py`);
`tests/code/network` + `database` + `storage` = **300 passed / 0 failed**; `tests/code/ui_services`
= 662 with 2 failures, **both proven pre-existing** (see §7).

---

## 6. What was deliberately *not* done

The original request asked for true DB-side paging — `ORDER BY imported_date DESC LIMIT 50`, with
sort and filter re-querying the database. That is the right long-term answer and it is **staged, not
done**, for a reason worth recording:

- The measured cost was **not** in the SQL. It was quadratic Python/Qt work in the render path.
  Fixing the render path first is where 3× lives; paging would have left every one of those costs
  in place for whatever page *was* rendered.
- Paging changes user-visible contracts that matter clinically: "select all" and "download
  selected" would cover only the loaded page; a column sort would have to become a re-query; the
  pinned-patient overlay and the persisted sort settings both assume a full table.

The user chose to keep the list auto-filling quietly in the background, so select-all, download-
selected and column sorting keep covering the **whole** result set.

**Remaining cost is now linear** — roughly 6 ms/row of genuine widget construction: 4
`setCellWidget` calls, ~16 `QTableWidgetItem`s, and a per-row `setStyleSheet` (a CSS parse per row).
Going materially below ~14 s for 2000 rows means either DB-side paging or a model/view
(`QAbstractTableModel` + delegates) instead of item widgets. Both are real projects; neither is a
tweak.

---

## 7. Pre-existing failures found along the way (not caused by this work)

1. **`test_status_report_sorting.py::test_status_flags_are_stashed_on_the_widget_to_avoid_recompute`**
   asserts `container.status_rank` appears within 1500 characters of
   `def _build_local_status_widget`. Extracting the same window from `git show HEAD` puts it at
   offset **2272 in both** HEAD and the working tree — the method's docstring grew during the
   2026-08-02 async-status fix and the guard's window never did. The guard is currently **not
   asserting what it believes it asserts**. Left alone here (unrelated system); worth widening the
   window to ~3000, the same repair applied to `test_cleanup_clears_pending_flag` in OPT-49.
2. **`test_report_assign_rendering.py::test_login_carries_the_user_identity_ids`** — untouched area;
   my diff's earliest hunk is ~800 lines below it.
3. **`tests/code/download_manager/test_instance_payload_key_variants.py`** fails to *collect*:
   `cannot import name '_INSTANCE_PAYLOAD_KEYS' from modules.download_manager.network.socket_client`.
   A collection error aborts the whole run, so `pytest tests/code` cannot currently complete without
   `--ignore`ing it. Unrelated to OPT-50, but it is blocking the merge gate.

---

## 8. Live verification checklist

1. Switch to **Local** on the real >2000-study database. The first rows appear immediately, and
   typing in the search box / changing a filter / switching tabs / scrolling all stay responsive
   while the rest fills in.
2. **Sort by Imported Date and let the list finish filling.** Every row must be in order — not just
   the first 20. This was silently broken before.
3. The **Assign** and **Report** columns must show the same icons, colours and tooltips as before.
   These come from the newly-cached JSON stores; if anything looks stale, `AIPACS_INO_STORE_CACHE=0`
   is the first thing to revert.
4. Change an assignment, then re-search — the new state must appear.
5. Import a study → the list refreshes without a freeze, and the imported study appears with the
   correct Status chips and Imported On stamp.
6. A pinned patient must survive a re-search and still appear once, at the top (the uid presence set
   is rebuilt from surviving rows precisely for this).
