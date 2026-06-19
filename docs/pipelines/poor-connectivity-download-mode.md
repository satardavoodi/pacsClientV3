# Per-server "Poor Connectivity" download mode (as-built, 2026-06-19)

A per-server toggle that makes downloads from a flaky / slow / unstable server
fetch **one image per batch** and retry at the **image level**, instead of
fetching multi-image batches that fail and re-fetch as a unit on a dropping link.
It reuses the *exact* mechanism of the existing large-frame-modality force-single
path, so there is **no new duplicate-download or DB/cache-consistency risk**.

## User-facing behaviour
- **Settings → Servers** (`server_settings.py`): each server has a checkbox
  *"Poor connectivity / unstable internet (download one image at a time)"*.
  Default **off**. Persisted in `config/servers.json` as
  `"poor_connectivity": true|false` on that server's record.
- When the **active** download server has it on: every series downloads with
  `batch_size = 1`, adaptive batch **growth is disabled**, and the existing
  atomic-write + R19 resume keep already-downloaded images and continue from the
  next missing one. Normal servers keep full adaptive batching (unchanged).
- It is **server-specific**: switch to a fast server and normal batching resumes.

## How the flag crosses the download-subprocess boundary
The download runs in a subprocess that connects to the socket host from
`socket_config.json` (`get_socket_server_settings()`), and that `socket_host`
equals the active server's host (e.g. razi `192.168.2.222`). So the flag is
resolved **by host**, against the host the subprocess actually downloads from —
no extra plumbing through `DownloadTask`/the queue, and it can't go stale.

`modules/network/socket_config.py`
- `SocketConfig.is_poor_connectivity_enabled(host=None)` resolves, first decisive wins:
  1. Env `AIPACS_POOR_CONNECTIVITY`: `1/true` → ON (manual override for a bad link
     now), `0/false` → OFF (master kill switch / legacy adaptive batching).
  2. The `poor_connectivity` flag on the `servers.json` record whose `host` matches
     the active `socket_host`.
  3. Default **False**. Any error → False (never breaks downloading). `get_all_servers`
     is imported lazily inside the method (no import cycle; subprocess-safe).
- Module-level `is_poor_connectivity_enabled()` delegates to the singleton.

## Where the batch size is pinned
`modules/download_manager/network/socket_client.py` (**plugin-mirrored** —
`tools/dev/sync_plugin_mirrors.py` + `verify_plugin_mirrors.py` after edits):
- `SocketDicomClient._poor_connectivity_active()` reads the resolver (lazy import
  of `modules.network.socket_config`), cached per client instance (the client is
  built per download task; the flag is per-server). Any failure → False.
- `download_series` computes once:
  - `_modality_force_single = _should_force_single_instance_batches(series_info)`
  - `_poor_conn = self._poor_connectivity_active()` → if set, `batch_size = 1`
    and a `[POOR_CONN] … batch_size=1 …` **WARNING** is logged (captured in
    `download_diagnostics.log`).
  - `_force_single = _modality_force_single or _poor_conn`.
- `_force_single` is then used at the only two other batch-size sites: the
  first-image-prime arg (`_first_image_prime_size(...)`) and the adaptive-growth
  gate (`and not _force_single`). The legacy modality predicate is now evaluated
  **once** — pinned by the guard test.

## Invariants (do not break)
- Poor-connectivity must behave **identically** to the modality force-single path
  (batch=1, no ramp-up); it adds **no** new write/resume logic. Atomic `.part` →
  `os.replace` + R19 resume already give image-level retry + keep-on-disk.
- The resolver must **fail to False**, never raise into the download loop.
- Keep `socket_client.py` and its plugin mirror in sync (frozen build reads the
  mirror's PYZ).
- The flag is resolved by the **active socket host**, not threaded through the
  task; if a deployment ever runs the socket service on a *different* host from
  the DICOM record, set `AIPACS_POOR_CONNECTIVITY=1` or align the hosts.

## Tests
`tests/code/download_manager/test_poor_connectivity_mode.py` (16) — resolver
precedence + per-server host matching + fail-safe, the `download_series` wiring,
the `[POOR_CONN]`/`batch_size=1` logging, UI persistence, and plugin-mirror parity.
Full `tests/code/download_manager` = **224 passed** (project `.venv`).
Env gate: `AIPACS_POOR_CONNECTIVITY` (`0` = legacy adaptive batching everywhere).
