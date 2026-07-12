# Radiography images will not display at a new center — a missing `SeriesNumber` killed the whole study

**Date:** 2026-07-12
**Center:** Roshana (newly installed)
**Severity:** HIGH — affected studies **never download**, so they can never be read
**Status:** FIXED, default-on. Needs live verification at the center.
**Master plan:** OPT-25 (§15)
**Evidence:** `C:\Users\Dr.Alizadeh\Desktop\log on other pc\logs roshana\logs\`
(`app.log`, `download_diagnostics.log`, `db_diagnostics.log`, `viewer_diagnostics.log`, `native_fault.log`)

---

## 1. Summary

A radiography (DX/CR) device at the new center writes DICOM **without a usable
`SeriesNumber` (0020,0011)**. The PACS server serializes that absent value as the
**literal string `"None"`**. Our socket metadata parser then executed

```python
series_number=int(str(series.get("series_number") or 0))   # grpc_client.py:147
```

`"None"` is a **truthy non-empty string**, so the `or 0` guard never fired and
`int("None")` raised `ValueError`. The exception escaped the per-series loop and
aborted the **entire study's** metadata build — not just that one series. Three
retries, then `Failed to fetch metadata`, so **the download never started and
there were no images to display.**

- It is **not** a network problem — the server answered in **38 ms**.
- It is **not** a decode, cache, or render problem — the pipeline never got that far.
  There is not a single decode/pixel/render error anywhere in the logs.
- The trigger is the **device/server data**; the **fatal behaviour is ours**.
  `SeriesNumber` is **optional (type 2)** in the DICOM standard — any device at
  any center may omit it, so the client must never assume it is a number.

---

## 2. Evidence chain

**`download_diagnostics.log`** — the socket is healthy, the parse is not:

```
[NET_TIMING] endpoint=GetStudyThumbnails payload_bytes=2146 server_wait_ms=38 transfer_ms=1 parse_ms=0 total_ms=39
❌ Metadata fetch via socket failed (attempt 1/3): invalid literal for int() with base 10: 'None'
❌ Metadata fetch via socket failed (attempt 2/3): invalid literal for int() with base 10: 'None'
❌ Metadata fetch via socket failed (attempt 3/3): invalid literal for int() with base 10: 'None'
❌ [COMPLETION] Download failed: 1.2.246.512.1000.959000462.1333101477.44...
❌ [ERROR]      Worker error:     1.2.246.512.1000.959000462.1333101477.44... - Failed to fetch metadata
```

**`db_diagnostics.log`** — the same value breaks the DB read path:

```
ERROR | PacsClient.pacs.workstation_ui.home_ui.home_db_service.get_series_info_from_database
      | Error getting series info from database: invalid literal for int() with base 10: 'None'
Traceback (most recent call last):
  File "PacsClient\pacs\workstation_ui\home_ui\home_db_service.py", line 146
ValueError: invalid literal for int() with base 10: 'None'
```

**`app.log`** — the affected study: patient `MOHAMMAD ALI`,
study `1.2.246.512.1000.959000462.1333101477.4464644671181596858`, **3 series**,
server `192.168.2.42:50052`.

**`native_fault.log`** — a secondary symptom: because the parse failure is
*deterministic*, the DM health check auto-retried it forever — **7 download
subprocesses spawned in 2 minutes** (11:11:27 → 11:13:23).

> Note on naming: `modules/download_manager/network/grpc_client.py` is **socket-backed**
> despite the legacy filename (`GrpcMetadataClient` → `PatientListSocketClient`, port 50052).
> gRPC is retired and is **not** involved in this failure. See §7.

---

## 3. Root cause

| Layer | File | What happened |
|---|---|---|
| Device | radiography DX/CR | omits `SeriesNumber` (0020,0011) — legal, it is type 2 |
| Server | PACS socket API | serializes the absent value as the **string** `"None"` (a `str(None)` leak) rather than JSON `null` |
| **Client (fatal)** | `modules/download_manager/network/grpc_client.py:147` | `int(str(x or 0))` → `int("None")` → `ValueError` → **whole study's metadata build aborts** |
| Client (silent) | `PacsClient/.../home_ui/home_db_service.py:146` | `int(series_number)` → caught, but the series info was silently lost |
| Client (cosmetic) | `home_db_service.py:115,123` | persisted `"None"` as the series number and created a folder literally named `None` |

The image download itself keys on **`series_uid`** (`GetSeriesImages{series_uid, batch_index, ...}`),
**not** on the series number — the number is only used for local naming, ordering
and display. That is why a purely client-side fix fully restores the study.

---

## 4. The fix — normalize once, at the single ingestion boundary

Every consumer of server series metadata — the download manager, the home panel,
the patient-tab thumbnails, previous-exams, the DB writer — reaches the server
through **one** pair of methods:

```
modules/network/socket_client.py :: PatientListSocketClient
    .get_study_thumbnails()      (GetStudyThumbnails)
    .query_series_thumbnails()   (QuerySeriesThumbnails)
```

So the repair goes **there**, and nowhere else. No consumer can then ever see a
non-numeric `series_number` again — one rule, no scattered exceptions.

### New: `modules/network/series_identity.py` (pure stdlib, unit-testable)

- **`parse_series_number(value)`** — the single tolerant predicate. Accepts every
  spelling a server may emit (`3`, `"3"`, `"03"`, `"3.0"`, `b"3"`), returns `None`
  for every way it can say "absent" (`None`, `""`, `"None"`, `"null"`, `"N/A"`, …).
  Never raises. **Do not re-implement `int(...)` on a server field anywhere else.**
- **`normalize_series_entries(payload)`** — repairs a study's series list in place
  and returns how many entries it had to repair (0 in the healthy case).

### Guarantees (this is what makes it safe for every other center)

1. **Byte-identical for good data.** A series whose number already parses is **not
   touched at all** — same value, same type. `"02"` stays the string `"02"`, so
   thumbnail/folder naming for every existing study is unchanged. Only unusable
   entries are rewritten. Healthy studies allocate nothing and log nothing.
2. **Non-colliding synthetic numbers.** A missing number becomes one from the
   reserved band **900001–999999** — far above any real `SeriesNumber`, and
   strictly **below `1_000_000`**, which is the multi-study *offset-key* threshold
   (`study_slot * 1_000_000 + series_number`, see `_vc_cache.py`). A synthetic
   number therefore can never be mistaken for an offset key, and numbers already
   used by the study are excluded, so two series can never collide — the exact
   class of bug that causes wrong-series display.
3. **Deterministic.** Synthetic numbers are assigned in **`series_uid` order**, not
   server-list order, so the UI process and the download subprocess — which fetch
   independently — always agree. The on-disk folder
   `SOURCE_PATH/<study_uid>/<series_number>/`, the thumbnail `<series_number>.png`
   and the DB row therefore stay consistent across sessions.
4. **Cannot break a fetch that would otherwise succeed** — normalization is wrapped
   and never raises.

### Defense in depth (so a *future* bad field can't do this again)

- `grpc_client._build_metadata_from_socket` now uses `parse_series_number` and wraps
  the **per-series loop in try/except**: a single malformed series is skipped with a
  warning, it can never abort the whole study's metadata again.
- `home_db_service.get_series_info_from_database` uses the tolerant parse instead of
  a bare `int()`.

**Kill switch:** `AIPACS_SERIES_NUMBER_NORMALIZE=0` restores byte-identical legacy behaviour.

---

## 5. Files changed

| File | Change | Mirrored? |
|---|---|---|
| `modules/network/series_identity.py` | **NEW** — pure stdlib authority | no |
| `modules/network/socket_client.py` | `_normalize_series_identity()` + wired into both series endpoints | no |
| `modules/download_manager/network/grpc_client.py` | tolerant parse + per-series guard | **YES** (download_manager package) |
| `PacsClient/pacs/workstation_ui/home_ui/home_db_service.py` | tolerant parse | no |
| `tests/code/network/test_series_number_normalization.py` | **NEW** — 15 guard tests | no |

---

## 6. Validation

- **`tests/code/network/test_series_number_normalization.py` — 15/15 green.**
  Pins the original `int("None")` crash; healthy payload byte-identical *including
  type*; no collision; below the 1e6 offset threshold; deterministic regardless of
  server list order; kill switch; wiring pins (the fatal cast can never come back,
  in the source **or** the plugin mirror).
- **`tests/code/download_manager` + `network` + `storage` — 499 passed**, 1 failure
  (`test_ino_report_workflow::test_classify_error[400]`) **proven pre-existing** — it
  fails identically with the edits `git stash`ed.
- **Zero regressions, proven by differential run.** `tests/code/{ui_services,viewer,builder,system}`
  were run **with** the fix and then again with the edits stashed:
  **65 failures before, 65 after, `Compare-Object` → IDENTICAL.** No new failure was
  introduced; those 65 are pre-existing environment/collection-order failures.
- **Plugin mirrors 412/412 match.**

### ⚠️ Sandbox hazard hit during this work (worth remembering)

The Linux sandbox FUSE mount served a **truncated** `grpc_client.py` (8344 of the real
9985 bytes, ending mid-statement) while still reporting the correct size — the
documented mount-staleness bug. Running `tools/dev/sync_plugin_mirrors.py` **inside the
sandbox** therefore wrote that **truncated file into the plugin payload**, silently
corrupting the build artifact. It was detected by compiling on the host, and re-synced
+ verified there.
**→ Always run `sync_plugin_mirrors.py` / `py_compile` / pytest on the Windows host.**

---

## 7. Follow-ups (NOT done)

1. **DM retries a deterministic failure forever.** A permanent parse/metadata error
   should be marked non-retryable — the health check respawned 7 subprocesses in
   2 minutes. Changing retry policy touches the download pipeline, so it is staged
   separately.
2. **Server-side (recommended, not required):** emit JSON `null` — or better,
   synthesize a `SeriesNumber` from the series index — instead of the string `"None"`.
   With the client fix in place this is now a cosmetic/robustness issue, not an outage.
3. **Rename the misleading module:** `grpc_client.py` → `socket_metadata_client.py`,
   `GrpcMetadataClient` → `SocketMetadataClient` (with a back-compat alias), so nobody
   chases a gRPC stack that has been retired. Plugin-mirrored — both copies move together.
4. Unrelated, but present in the same logs: `❌ [RECEPTION] Reception data fetch failed:
   Connection error` — the reception/RIS API is not reachable from that center.

---

## 8. Live verification at the center

Open patient **MOHAMMAD ALI**, study `1.2.246.512.1000.959000462.1333101477.4464644671181596858`.

**Expect:**
- `app.log`: `[SERIES_NUMBER_NORMALIZE] endpoint=GetStudyThumbnails study=… repaired=N
  reason=server_sent_unusable_series_number` — logged **once per fetch**, only for the
  affected study.
- `download_diagnostics.log`: **no** `invalid literal for int()`, **no**
  `Failed to fetch metadata`; a normal download run to completion.
- The radiography images display.
- Other patients/centers: **no** `[SERIES_NUMBER_NORMALIZE]` line at all (healthy data
  is untouched) and no behavioural change.
