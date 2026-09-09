# UI Stall Evidence and Guarded Fixes — 2026-09-02

## Scope

This report reconciles the 2026-09-02 source-build performance logs, recovered Cloud
decision history, current code, focused tests, and the subsequent source-build live run. It
contains no patient identifiers or clinical payloads. It does not claim installed-build,
release, or clinical-workflow verification.

## Corrected evidence baseline

- 711 measured UI gaps exceeded 100 ms; median 169.2 ms, p95 562.1 ms, 11 above 1 s.
- Only four traces occurred during a drag interval and none recorded `drag_active=True`.
- Fast Viewer handler time remained healthy: median `total_ms` 32 ms, p95 70 ms. No Fast
  decode/render change was justified.
- `first_series_visible` is emitted again during rerender. Across 16 open requests there were
  31 markers; using every marker produced a false multi-second median. The first marker per
  session is the valid TTFF sample, approximately 528 ms median in the corrected analysis.
- The program connection explicitly uses `PRAGMA synchronous=NORMAL`. A raw diagnostic
  connection reported `2/FULL`; it did not represent application behavior.
- Today's four access violations belonged to AI-PACS-owned subprocess PIDs absent from the
  main `app.log` session list. Six `0x8001010d` events belonged to main sessions and were
  non-terminal. Whole-file historical totals are not current-day crash counts.

## Rev 3 live verification

The source-build run reduced the count of recorded gaps above 100 ms from 711 to 218. The
p95 moved from 562.1 ms to 706.4 ms, so the result must not be described as a uniform
percentile improvement: removing many small stalls changes the remaining distribution. The
defensible improvement is the lower event count and the absence, in the exercised paths, of
the eight named pre-fix stacks. Eagle Eye was not exercised, so absence of its probe stack is
not independent live proof.

Confirmed in the observed run:

- root theme application completed in 3.4 ms;
- the retired gRPC import, adapter discovery, synchronous voice write, patient-tab
  pixel-less-stub scan, and Zeta WAL first-touch stacks did not recur;
- three approved voice recordings were published successfully;
- the visit-status worker completed its observed write in 24.75 ms without blocking the Qt
  thread;
- six patient opens produced one valid first-visible marker per open, with median TTFF
  642.8 ms, p95 1089.1 ms, and maximum 1144.2 ms;
- Fast Viewer and drag-handler timings remained healthy enough to exclude them as the cause
  of the remaining multi-second stalls;
- no terminal main-process native crash or Windows hang was observed. One caught,
  non-terminal `0x8001010d` marker remained.

The status is **partially live-verified**, not complete.

## Root causes and corrections

### 1. Visit-status SQLite write

Evidence showed 2332.9 ms inside `set_visit_status` from the Qt main thread, accounting for
about 83% of the corresponding 2818 ms open interval. OPT-45 already gives the main process a
5000 ms busy timeout and download subprocesses 120000 ms. The delay was a WAL write-lock wait
inside that bounded ceiling, not a durability setting.

Correction:

- `visit_status` is created/migrated by `init_database`;
- the per-open writer no longer performs a nested schema check;
- the table colour updates immediately;
- persistence runs through one ordered worker, preserving `opened -> synced` order without
  multiplying SQLite writers.

The live run also exposed a separate, pre-existing persistence defect. `set_visit_status`
has always used `UPDATE studies ... WHERE study_uid = ?` and still returns
`cur.rowcount > 0`. A server-only study with no derived local `studies` row therefore returns
false. Before OPT-58 the UI still became orange and this failed persistence was silently lost
at restart; the asynchronous writer made that old failure observable. It is **not an OPT-58
regression**. `ensure_visit_status_column()` is confirmed absent from this hot path.

Do not repair this by fabricating a stub row in `studies`: that table is a derived disk index
that reconcile/resync may rewrite or remove. The future persistence boundary should be an
independent table such as
`study_visit_status(study_uid TEXT PRIMARY KEY, status TEXT, updated_at)`, with no foreign key
to `studies`, while preserving the rule that a stale `opened` write cannot overwrite `synced`.

Rollback: `AIPACS_VISIT_STATUS_ASYNC=0` restores synchronous persistence for diagnosis only.

### 2. Startup native gRPC import

Importing any `PacsClient.components.*` submodule executed package-level compatibility exports,
which loaded the retired gRPC downloader. One trace spent 3493.9 ms importing
`grpc._cython.cygrpc` on the UI thread.

Correction: compatibility exports use lazy module attributes. Public names remain available,
but importing a loading overlay no longer imports gRPC, Download Manager, Zeta, or the module
system.

### 3. Startup root stylesheet repolish

The completed control-panel tree received a root `QMainWindow` stylesheet after construction.
Measured sessions spent approximately 1.45-2.49 s in this repolish family.

Correction: the redundant post-build root stylesheet was removed. The same window background is
set with `QPalette`; child theme styles and theme-change behavior remain explicit and unchanged.

### 4. Enabled Agent Gateway address/TLS preparation

An enabled source configuration called `psutil.net_if_addrs()` while constructing the home panel;
one trace blocked the GUI for about 1443 ms.

Correction: the Qt command dispatcher is prepared on the UI thread, then adapter discovery, TLS
identity work, and transport binding run on a daemon startup thread. Default-off and shutdown
ownership are unchanged.

### 5. Patient-tab activation manifest scan

`on_tab_activated` synchronously called the authoritative completeness manifest. On a cache miss,
pixel-less-stub verification walked the series filesystem; a measured trace spent about 443 ms.

Correction: the complete, content-aware manifest decision runs on a worker. A generation token and
active-tab check discard late results. Pixel-less-stub detection, DB/disk authority, pipeline state,
and warmup gating remain unchanged.

### 6. Zeta manifest SQLite first touch

Every Zeta manifest connection executed `PRAGMA journal_mode=WAL`; construction and close traces
showed roughly 0.4-2.5 s in `_conn()` on the GUI thread.

Correction:

- schema/WAL first touch runs on a daemon worker;
- WAL is configured once rather than on every connection;
- reads before readiness degrade to an ordinary cache miss;
- background writes wait for bounded readiness;
- close does not queue a late clear, avoiding same-key close/reopen deletion races;
- slow schema initialization emits a PHI-safe timing marker.

### 7. Voice WAV flush

Stopping an inline recording called `sf.write` on the GUI thread. Native `sf_write_sync` produced a
410.4 ms trace.

Correction: queue draining still happens synchronously before stop completes, but WAV serialization
uses a daemon worker and a sibling temporary file followed by atomic replace. Explicit delete cancels
publication; non-user teardown does not delete an approved recording; Sync waits for publication.

### 8. Eagle Eye eager secondary tabs and series probe

`AiMainWindow` eagerly constructed Imaging Tools, Data Set, Model Training, and Reception Data.
Series probing also enumerated each folder twice and performed `pydicom.dcmread` on the GUI thread;
one measured probe gap was about 430 ms.

Correction:

- Imaging Tools remains the only eager active tab;
- the other three tabs retain stable positions but import/construct only when selected;
- DICOM candidate probing runs on a worker and uses a generation guard at teardown;
- the GUI thread supplies only an immutable identity/geometry snapshot; the worker never
  dereferences the live patient widget or receives VTK/private metadata;
- each series folder and its file list are enumerated once.

## Guard evidence

The new focused selection failed before production changes with 11 failures. It demonstrated the
blocking visit write, missing startup migration, eager gRPC import, root stylesheet, synchronous
gateway start, inline manifest scan, synchronous Zeta schema work, inline WAV write, eager Eagle Eye
tabs, inline Eagle Eye probe, and double series enumeration.

After the corrections and the final thread-boundary hardening:

- dedicated new guards: 13 passed (the original fail-before set contained 11 boundaries);
- voice/DB/theme/gateway/Eagle Eye adjacent boundary: 130 passed;
- Eagle Eye probe/training/dataset boundary: 176 passed;
- database plus visit-status boundary: 14 passed;
- current adjacent startup/gateway/database/Eagle Eye selection: 340 passed;
- all 462 packaged plugin mirror pairs match after syncing the Zeta payload;
- builder-focused checks: 17 passed, with one unrelated pre-existing failure because the
  existing staged `patient_table_sort.json` is stale;
- Python compilation of every changed runtime module: exit 0.

## Remaining gates

The live run found four remaining workstreams:

1. **Server-search row construction — fixed/offscreen verified, live pending:** after the server returned 51 rows, synchronous
   `count_subfolders_with_dicom` traversal on the GUI thread produced the largest remaining
   confirmed freeze. This is the third occurrence of the same design error already seen in
   `_pixelless_stub_count` and the Eagle Eye probe: answering a UI question by synchronously
   walking the filesystem. The 2026-08-22 work already replaced the expensive `rglob` scanner
   and moved later status refreshes behind `downloadStatusReady`; it did not cover the initial
   server-search row-construction call. Code review then proved its synthesized
   `download_status`/`is_downloaded` fields were unused: `add_patient_data` already paints an
   empty Status cell and resolves the authoritative disk flags through `statusFlagsReady`.
   Removing the redundant call was safer than adding another batch, cache, or invalidation path.
   Explicit Local/Import state is forwarded unchanged. The fail-before guard observed one probe;
   the corrected 51-row controlled replay observed zero. Live acceptance is a fresh Server Search
   with no `get_study_download_status/count_subfolders_with_dicom` UI stack and correct eventual
   DICOM chips.
2. **Server-only visit-status persistence:** use the independent table described above, not a
   fabricated `studies` row. This requires a fail-before guard and migration/reconcile tests.
3. **Definitive download completion:** the observed run included genuine no-response failures
   and preemption cancellations, but no authoritative completion marker. Download integrity
   therefore cannot be asserted from the log. Add the explicit completion marker before any
   further download-path optimization; it becomes the pass/fail probe for future soak runs.
4. **MPR/VTK:** retain this as a separate execution-domain workstream. Instrument construction
   and volume-build stages first, then optimize from measured evidence.

Additional live gates remain for Eagle Eye lazy-tab/probe behavior, direct Zeta
`_conn()`/`clear_tab` instrumentation, and startup `window.show`, icon, and font first-touch.
The revised order is: live-verify the Server Search fix, server-only visit persistence, download
completion marker, Eagle Eye live pass, MPR instrumentation, Zeta instrumentation, then remaining startup
first-touch work. Every behavioral change requires its own fail-before guard.

The installed executable and heavyweight release builder were not launched. The existing staged
build remains non-authoritative until its unrelated stale configuration is rebuilt from a clean
release candidate. OPT-58 did not change Download Manager, Fast Viewer, DICOM decode, server
protocol, or clinical geometry behavior. The download completion-marker requirement above is an
open follow-up, not an implemented change.
