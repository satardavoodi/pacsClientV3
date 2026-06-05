# Stability Fixes — Instance Takeover + Large Radiology Batches (2026-06-05)

Two user-reported high-priority issues, both fixed in source, compiled,
guard-tested, and plugin-mirrored (287/287).

## 1. Force-close old instances on new launch (TAKEOVER policy)

**Problem:** old AI-PACS processes survive hibernate / power failure / crash /
improper close and interfere with the next launch (DB locks, download
conflicts, "already running" blocks, hidden Task Manager leftovers).

**New behavior (default, no dialog, no question):** the new launch always wins.

`PacsClient/utils/single_instance_lock.py` — `try_acquire` now:

1. **Quiet probe** of the QLocalServer name (connect-only — the doomed old
   window is not raised first).
2. **Graceful close first:** sends a new `AIPACS_SHUTDOWN` IPC message. The
   old instance (this build onward) quits through the event loop, so the
   run-loop `finally` performs the full clean shutdown — DB WAL checkpoint,
   download-subprocess termination, lock release — with an 8 s hard-exit
   failsafe (honors `AIPACS_NO_HARD_EXIT`).
3. **Force-kill fallback** after ~6 s: a psutil sweep terminates+kills every
   other top-level AIPacs **process tree** — frozen exes (`aipacs.exe`,
   `AI PACS Viewer.exe`), source runs, and crucially **orphaned download
   workers / pre-warm spares** that re-exec a relative `main.py` (matched via
   interpreter path / cwd). Never self, ancestors, or descendants; other-user
   processes are skipped.
4. The same sweep also runs when nobody is listening (crash leftovers that
   never owned the pipe — exactly the hibernate/power-failure debris).
5. **No kill loops:** if `listen()` still fails afterwards, the launch
   re-pings and defers to the (even newer) winner quietly.

Old production builds don't understand `AIPACS_SHUTDOWN`? They don't need to:
step 3 covers them — important because the next shipped build will be doing
takeover against today's frozen builds.

Safety rails: `AIPACS_NO_TAKEOVER=1` restores the legacy raise-window
behavior; under pytest takeover is hard-disabled (a test can never kill the
test runner or your live session). The "AIPacs Already Running" dialog no
longer appears in takeover mode.

Docs updated: `SINGLE_INSTANCE_GUARD_2026-06-02.md` (addendum) + `CLAUDE.md`.

## 2. Large radiology download batches stall / freeze

**Investigation answers (per the requested checklist):**

| Area | Finding |
|---|---|
| Client-side buffers | **ROOT CAUSE — O(n²) freeze.** The body recv loop did `bytes += chunk`. A 300 MB radiology batch in 64 KB chunks ≈ terabytes of memcpy → **minutes of CPU that looked exactly like a stuck download**, scaling with payload² — why big X-ray batches specifically. Fixed: `bytearray.extend` (linear). |
| Batch size | Count-based only (10): ten 30–40 MB DX/XA frames = 300–400 MB single JSON response. Fixed: per-series **64 MB byte-budget soft cap** — an oversized batch halves all subsequent batches of that series (applied after the index advance, so server `batch_index` alignment is preserved; never written to the global adaptive size). |
| Modality routing | `XA` (angio), `RF` (fluoro), `DR` were missing from the forced single-image-batch list (CR/DX/MG/PX were covered). Added. |
| Server response limit | The 500 MB client cap raised "Response too large" — which **never reached the halving logic** (swallowed into `None` by `send_request`); series failed as opaque "No response" (16 production hits). Fixed earlier today (U1): structured error for `GetSeriesImages` → halving fires; at minimum batch size, 2 bounded same-size retries on a fresh socket (an implausible length usually means stream desync, and the socket is already dropped at the raise site). |
| Timeout handling | Sound: 30 s socket timeout applies per recv; slow-but-flowing data never times out; a stalled link aborts the chunk within 30 s. |
| Retry logic | Sound: 3 attempts per batch with exponential backoff + jitter + reconnect; health-monitor throttling; series-level re-queue above. |
| Partial downloads / resume | Sound: atomic `.part` → `os.replace`, file-level skip, verified leading-batch skip. A failed batch loses only that batch. |
| Memory pressure | JSON+base64 peak ≈ 3× payload. With the 64 MB cap the peak is ~200 MB instead of >1 GB — survivable on low-RAM clinic machines (same machines as the Eagle Eye allocation crash). |
| Disk write time | Sound: timed, atomic, off the GUI process. |
| Slow networks | Per-chunk timeout + retries + resume mean a slow link degrades to slower-but-progressing, not stuck; the cap keeps individual responses small so each retry risks less. |

**Net effect:** large X-ray/angio/fluoro series download in single-image
batches; any other oversized series self-tunes its batch size downward; the
quadratic freeze is gone; "Response too large" recovers instead of failing;
failures surface their real reason in the DM.

## Verification

| Check | Result |
|---|---|
| `tests/code/test_single_instance_takeover.py` (matching rules ×6, env gates ×2, source contracts ×3) | **11/11 passed** |
| `tests/code/download_manager/test_large_batch_stability.py` (incl. 100 MB linear-accumulation timing test) | **6/6 passed** |
| Full `tests/code/download_manager` regression | **125 passed** |
| `py_compile` single_instance_lock / socket_client / main.py | OK |
| `tools/dev/verify_plugin_mirrors.py` | **287/287** |

## Live-validation notes (next launch)

- Takeover: with the app already running, launch a second time → the old
  instance closes itself (log: "taking over (new launch wins)" then
  "Received SHUTDOWN from a newer AIPacs launch") and the new one continues.
  Kill-test: `taskkill /f` the app mid-run, relaunch → startup sweep log line.
- Large batches: download an XA/RF/DX-heavy study on a slow link → expect
  single-image batches (or a `📉 …exceeds 64 MB soft cap` warning for
  non-listed series), steady progress, no multi-minute silent gaps in
  `download_diagnostics.log`.
- Both fixes are source-only until the next frozen build ships.
