# B5 — download↔viewer DB-write contention: investigated, NOT a bottleneck (no change)

**Date:** 2026-06-21  **Commit base:** `beta-version` @ `56ca5eec`
**Outcome:** **No code change.** Evidence shows the DB concurrency layer is healthy; changing the live clinical DB's write/transaction logic for a non-problem would add regression risk with no measurable benefit.

## What B5 suspected

The performance evaluation flagged DB-write spikes (`transaction_scope` max 18.6 s, `save_series_instances`/`batch_insert_instances` max ~6.9 s, `create_connection` max 2.3 s) as possible download-subprocess↔viewer contention on the shared `dicom.db`.

## What the evidence shows

- **`database is locked` = 0** across **all** `db_diagnostics.log*` + `download_diagnostics.log*` (entire history). SQLite-level write-lock contention is not occurring.
- **`pool_lock_wait`: never logged** — every pool-lock acquisition was under the timing threshold (the connection-pool lock is not a contention point).
- **`transaction_scope` > 3 s: only 5 occurrences ever** (one 18.6 s write, plus ~3–4 s: 3 writes, 1 read). `transaction_scope` measures the **whole `get_db_connection()` held duration** (caller work while holding a pooled connection), **not** lock-wait — so these are rare long-held connections during heavy batch writes, not blocking.
- WAL mode means readers run concurrently with the single writer (readers use the last-committed snapshot), and the download subprocess + main app already share the DB with `busy_timeout=120 s` + capped exponential retry/backoff (`database/_pool.py`).

## Why no change

The premise (contention hurting the pipeline) is not borne out: **zero lock contention, zero pool-lock waits, 5 rare long-held connections in the entire log history.** The concurrency layer is doing its job. The DB layer is also the highest-severity area for clinical-data integrity (the test-pollution history), so a speculative change to write batching / transaction granularity / WAL settings would risk a real regression to fix a non-issue. Per the "be careful not to regress" priority, B5 is closed as **investigated, no change warranted.**

If a genuine DB stall ever appears, the signal to watch is `database is locked` (currently 0) and `pool_lock_wait` (currently sub-threshold) in `db_diagnostics.log` — not the `transaction_scope` max, which is a held-duration metric.

## Plan status (final, client-side)

- ✅ **B2** prime alignment — default-ON, live-validated.
- ✅ **Wrong-study** drag fix — default-ON, live-validated.
- ✅ **B6** oversize fast-fail — implemented, default-off (rare case; not yet exercised).
- ✅ **B4** multi-study DB-first metadata — implemented, default-off; **needs a multi-study validation run** (open a patient with ≥2 studies / Previous Exams with the verify flags).
- ⏹ **B5** DB-write contention — **investigated, not a bottleneck, no change.**
- ⛔ **B1** re-enable batch growth — requires a **server-side stable-pagination** change first; cannot be done safely client-only.

**Net:** every client-side optimization that can be done safely is done. The only remaining latency lever (B1) needs a server change; B5 is a non-issue. Outstanding action is the **B4 live validation** on a multi-study patient.
