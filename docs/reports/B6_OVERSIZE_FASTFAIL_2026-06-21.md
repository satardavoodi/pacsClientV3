# B6 — oversized-single-instance "Response too large" fast-fail (staged, default-off)

**Date:** 2026-06-21  **Commit base:** `beta-version` @ `56ca5eec`
**Status:** implemented behind a default-OFF flag; offscreen-tested. Live validation is hard to stage (needs a genuinely oversized instance), so it is **safe to enable** but its real-world effect is only seen when an oversized instance occurs.
**Scope:** the inner batch-retry wrapper only. Preserves stream-desync recovery, normal-batch retries, and all other error handling.

## What this fixes

When the server's response for a request exceeds the 500 MB hard cap, the client rejects it on the 4-byte length header (fast) and raises `Response too large`. For a **single oversized instance** (`batch_size == 1`, e.g. a 558 MB instance) this is **deterministic** — retrying the same instance always hits the same cap. Today `_download_batch_with_retry` treats it as a transient error and loops `MAX_RETRIES` with escalating backoff + reconnect (~30-40 s/call), and the coordinator re-attempts the series on top, so a doomed series can churn for **minutes** (observed ~7m45s) before failing anyway.

Crucially, a `> 500 MB` length can ALSO mean a **stream desync** (the 4 length bytes were really payload), which a fresh socket recovers — so the retry can't simply be removed.

## The change

`modules/download_manager/network/socket_client.py` (+ plugin mirror), in `_download_batch_with_retry`'s exception handler:

- New flag (default OFF): `_FASTFAIL_OVERSIZE = os.getenv("AIPACS_FASTFAIL_OVERSIZE","0") == "1"`.
- When enabled AND `batch_size <= 1` AND the error is `Response too large`: allow **exactly one** quick fresh-socket reconnect (covers a genuine desync), and on the second occurrence (or last attempt) **return fast** (no further doomed retries). A per-call counter `_oversize_seen` enforces the "one reconnect" budget.

Everything else is unchanged: multi-image batches (`batch_size > 1`) still shrink/retry, and all non-too-large errors keep the full R27/R28 exponential-backoff + reconnect path.

## Why it is safe

- **Desync recovery preserved.** One immediate fresh-socket reconnect is enough to resync a desynced stream (a clean socket reads a valid length); the fix keeps exactly that.
- **Genuine-oversize identified narrowly.** Only `batch_size <= 1` + `Response too large` is treated as deterministic. A real oversized single instance fails the same way it does today — just in seconds, not minutes.
- **No data-loss risk.** This path only ever *fails* a series that was going to fail anyway (the instance exceeds the server cap); it never drops instances from a recoverable download. Atomic writes/resume unchanged.
- **Default OFF** ⇒ production byte-identical until enabled.
- **Out of scope (unchanged):** the coordinator's series-level re-attempts. The fix shortens each attempt (the inner compounding) but does not reclassify the failure as permanent (a desync IS legitimately retryable), so it cannot regress the desync case.

## Verification done (offscreen)

- Syntax OK; plugin mirror synced + **verified 390/390**.
- `tests/code/download_manager`: **256 passed** with the flags **off (default)** and **on** (`AIPACS_FASTFAIL_OVERSIZE=1` + `AIPACS_PRIME_ALIGN=1`).
- New tests `tests/code/download_manager/test_oversize_fastfail.py`: flag default-off pin, single-instance scope pin, one-desync-reconnect-preserved pin, legacy-path-intact pin.

## Enable / validate / rollback

- **Enable:** set `AIPACS_FASTFAIL_OVERSIZE=1` and restart the source build.
- **Observe (only when an oversized instance occurs):** `download_diagnostics.log` shows one `… one quick reconnect (stream-desync recovery) then fail fast` then a fast series failure, instead of minutes of `Retrying in Ns…` / repeated `Response too large`.
- **Rollback:** unset the flag (or `=0`) — instant revert to the full backoff-retry.

## Plan status (staged optimizations)

- **B2** (prime/pagination alignment) — implemented, default-off, offscreen-green; **awaiting your live validation** (`AIPACS_PRIME_ALIGN=1`, drag a not-downloaded N≡1-mod-10 series, confirm no `INCOMPLETE_SERIES`). See `B2_PRIME_PAGINATION_ALIGNMENT_2026-06-21.md`.
- **B6** (this) — implemented, default-off, offscreen-green.
- **B4** (multi-study DB-first metadata) — still staged; needs golden-compare geometry validation.
- **B5** (download↔viewer DB-write contention) — still staged; needs measurement.
- **B1** (re-enable safe batch growth) — still staged; needs server-side stable pagination first (data-loss risk otherwise).
- **Open correctness item (separate from perf):** the wrong-study drag bug (`PIPELINE_DRAG_EXACT_SERIES_ANALYSIS_2026-06-21.md`) was analyzed but **not fixed**; it could not be re-verified in the latest session because `AIPACS_VIEWPORT_LOAD_TRACE` was off.
