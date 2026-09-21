# AI-PACS Cloud Decision Ledger

**Last reconciled:** 2026-09-18 (single active Unify queue)
**Audience:** Claude Projects, Codex, local coding agents, and maintainers
**Privacy:** PHI-safe summaries only; never copy raw clinical conversations or logs here

## Purpose and precedence

The recovered Cloud archive contains useful decision history, rejected approaches, and
incident rationale that are not always visible in the current source tree. It is supporting
history, not a second source of truth.

When sources disagree, use this order:

1. current runtime code and configuration resolution;
2. executable focused tests and release gates;
3. current as-built repository documents;
4. this ledger;
5. recovered Cloud transcripts and historical reports.

The recovered snapshot is under
`D:\_RECOVERY\restored\projects\ai-pacs-workstation` and was generated on 2026-08-27.
It cannot contain decisions created after that date. The 2026-09-02 performance-verification
Claude Project document was never present in the checkout or recovery snapshot; its corrected,
PHI-safe repository counterpart is
`docs/reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md`.

## Curated decisions

| Topic | Durable invariant | Cloud/recovery value | Current verification | Status |
|---|---|---|---|---|
| Shared Unify execution order | Only one shared-trunk behavior slice is active at a time: U0 accept landed Local/handoff work, U1 authoritative download completion, U2 primary state authority, U3 invalidation bus, U4 chokepoint/path retirement, U5 installed/restart/stress closure. A failed gate extends its existing owner; it never creates another producer, cache, callback, downloader or plan. Native shutdown failure pauses the queue and stays in the crash/lifecycle owner until attributed. | Preserves the user's directive that continuing improvements must follow one decision path rather than accumulating parallel staged plans or duplicated repair routes. | `UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md` current ledger; optimization master plan 2026-09-18 entry; current code still shows partial state authority and scattered invalidation | Current; U0 code-verified, fresh source GUI/KPI and normal-exit gate open |
| SQLite lock waits / OPT-45 | The main GUI process uses a short busy timeout; download subprocesses retain 120 s. Do not change durability or lengthen the subprocess timeout to treat a GUI-thread write. Move the specific write off the GUI thread. | Preserves the original role-aware timeout rationale and the distinction between WAL readers and writers. | `database/_pool.py::_resolve_db_timeouts`; `tests/code/system/test_db_main_busy_timeout.py`; the 2026-09-02 `set_visit_status` trace | Current |
| Visit status | Schema migration belongs to startup. Patient-open colour is immediate; persistence is ordered and off-thread. Never run `ALTER TABLE` or a lock-waiting commit in the open handler. `UPDATE studies ...` returning false for a server-only study is a pre-existing silent persistence defect made visible by OPT-58, not an OPT-58 regression. Do not fabricate a `studies` stub: future persistence belongs in an independent `study_visit_status(study_uid, status, updated_at)` table with no foreign key, and `synced` must remain monotonic over stale `opened`. | Explains why OPT-45 bounded but could not eliminate a UI-thread write-lock wait and why the derived disk index must not become UI-owned state. | `database/dicom_db.py`, `database/manager.py`, `patient_table_widget.py`; `test_visit_status_write_off_ui.py`; 2026-09-02 live run | Current UI-stall fix; persistence follow-up open |
| UI filesystem questions | Never answer a row, tab, or capture-readiness question by synchronously traversing the filesystem on the Qt thread. Reuse the content-aware worker/cache boundary shared by completeness work; do not create another scanner. The 2026-08-22 optimization covered the scanner and later refresh path; on 2026-09-02 the uncovered initial Server Search caller was removed because its derived fields were unused and the existing Status worker already owned the answer. | Unifies the recurring `_pixelless_stub_count`, Eagle Eye probe, and `count_subfolders_with_dicom` failure pattern without misclassifying the uncovered initial-row seam as a full regression of the earlier fix. | 2026-09-02 live stack; `modules/storage/sync_manifest.py`; 29 `test_gui_thread_disk_paths.py` guards; Eagle Eye probe guards | Current invariant; Server Search fix code/offscreen verified, live pending |
| Download completion evidence | A download run is not verifiably complete until an authoritative marker states that the frozen study manifest is satisfied on disk. Timeouts, preemption, progress totals, and absence of errors are not substitutes. Land this marker before further download-path optimization and use it as the soak pass/fail probe. | Prevents performance work from making an unsupported study-completeness claim. | OPT-57 manifest/progress contract plus 2026-09-02 live-run observability gap | Open follow-up |
| Eagle Eye secondary tabs | `ImagingToolsTab` is the active reading surface. Data Set, Model Training, and Reception Data are secondary and must be constructed only when selected. | Recovered analysis measured the Model Training widget's pure Qt and storage cost and explicitly staged lazy construction. | `ai_mainwindow.py`; `test_ui_stall_boundaries_2026_09_02.py` | Current |
| Eagle Eye DICOM probe | Series discovery must enumerate each folder once and read headers off the GUI thread. The worker receives an immutable identity/geometry snapshot, never a live patient widget, VTK object, or private metadata. A stale result must not start capture after teardown. | Preserves the reason for header probing rather than loading every series into a viewer. | `series_probe.py`, `workflow_coordinator.py`; generation guard and focused probe tests | Current |
| Pixel-less DICOM stubs | Pixel-presence verification is a correctness invariant. Optimization may cache or move it off-thread but must not remove or weaken stub detection/invalidation. | Records why small header-only image objects cannot count as completed pixel instances. | `modules/storage/sync_manifest.py`; tab activation now computes the same authority on a worker | Current |
| Native fault classification | `0xc0000005`/access violation is a native crash. `0x8001010d` is a caught, non-terminal COM reentrancy warning. Count by session and correlate PID ownership before assigning a crash to the main process. | Corrects older reports that mixed whole-file history, current-day sessions, and subprocess markers. | Current `CLAUDE.md` native-fault section and 2026-09-02 PID/session review | Current |
| Zeta manifest cache | Cache identity remains `(tab_key, series_number)`. Never introduce a late asynchronous `clear_tab` that can erase a newly reopened tab with the same key. SQLite WAL configuration is one-time schema work, not a per-connection GUI operation. | Preserves cache identity and close/reopen race rationale absent from short code comments. | `modules/zeta_boost/disk_cache.py`; schema initialization is off-thread and early reads fail safely as cache misses | Current |
| Qt asynchronous lifetime | Background results require generation/liveness checks. A stale callback must never touch a rebuilt row, closed patient tab, or deleted widget. | Recovered Shiboken/search incidents show the concrete failure family. | Existing Local-search generation guards plus the 2026-09-02 activation/probe generation checks | Current |
| Thumbnail manager ownership / OPT-60 | Retire owner callbacks and generation-scoped deferred work explicitly. Native card children remain parented until normal deletion; Ready timers are UI presentation, not completion authority. | Recovered history explains inverse teardown, not proof that historical P1 implemented manager cleanup. The card has `theme_manager` but lacked its referenced callback, so the old outer catch skipped cleanup; the earlier absent-attribute explanation was incorrect. | Patient signal relay, manager reset/dispose and card-effect retirement are now guarded. Latest 14 card Qt guards; 441 expanded passes / 1 existing skip, 462 mirrors match. See canonical OPT-60 for original fail-before evidence, exact scope and rollback. | Code PASS; fresh-source GUI pending after the 20:41 run. Direct map clears, worker-image identity, native crash/stress and installed acceptance remain open |
| Voice WAV persistence | Queue draining remains mandatory. Native WAV flush is filesystem I/O and runs off the GUI thread; explicit delete cancels an unpublished temp file while teardown preserves an approved recording. | Retains the original short-recording/tail-loss rationale. | `voice_tool_ui.py`; voice queue/delete/study guards | Current |

## Explicitly superseded Cloud material

Do not import or act on the following without reconciling it against current code:

- old version numbers, paths, test counts, and module inventory;
- the statement that `run_test.ps1` is authoritative proof of success;
- older `RPC_E_WRONGTHREAD` or whole-history native-fault interpretations;
- raw patient identifiers, DICOM metadata, screenshots, reports, credentials, or log excerpts;
- any historical plan that conflicts with current execution-domain or packaging rules.
- the May/June 2026 claim that `thumbnail_manager.py` had a manager-level P1 cleanup or that a
  six-cycle soak proved that ownership boundary closed.

## Adding a Cloud-derived decision

Add only a short PHI-safe entry with all of the following:

1. topic and immutable engineering invariant;
2. recovered source date or conversation identifier without patient data;
3. current code/test verification;
4. status: `Current`, `Superseded`, or `Historical only`;
5. regression guard or live gate.

Never bulk-copy transcripts. Keep the archive read-only and preserve its provenance.
