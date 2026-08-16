# The L2 disk pixel cache now survives shutdown

**Date:** 2026-08-16
**Status:** fixed, guarded, reversible
**Decision:** taken by the product owner — persistence ON by default
**Files touched:** `modules/viewer/fast/disk_pixel_cache.py` (new method),
`PacsClient/pacs/workstation_ui/mainwindow_ui.py` (one call site)
**Guard test:** `tests/code/viewer/test_disk_pixel_cache_persistence.py` (20 guards)
**Kill switch:** `AIPACS_PIXEL_CACHE_CLEAR_ON_EXIT=1` restores the old wipe-on-exit

This resolves §1 of [`OPEN_FINDINGS_2026-08-16.md`](OPEN_FINDINGS_2026-08-16.md).

---

## 1. The bug

`MainWindowWidget._shutdown_caches()` (`mainwindow_ui.py:1521`) ended with:

```python
get_disk_pixel_cache().clear()
```

`DiskPixelCache.clear()` is not a cheap index reset — it calls
`shutil.rmtree(self._root)` and recreates an empty directory
(`disk_pixel_cache.py:306-321`). Every decoded slice on disk was deleted on
every exit.

The module it was deleting describes itself as:

> **L2 persistent cache** for decoded DICOM pixel arrays. Eliminates the need
> to re-decode slices when reopening a previously-viewed series.

It is built for persistence — a 2 GB cap, LRU eviction by last-access time, a
corruption-safe binary header, an on-disk index scan at startup. The one thing
it needs to deliver any of that is to still be there next time.

## 2. Evidence it never was

Every `cleared` and `indexed` line in `viewer_diagnostics.log*`:

```
2026-08-08 15:21:56 / 16:14:41 / 17:37:18 / 20:22:06   cleared
2026-08-09 12:26:14 / 15:21:19 / 17:19:25 / 18:27:17
             / 19:07:08 / 19:45:12 / 21:19:00 / 22:48:14   cleared
2026-08-10 15:31:22 / 21:30:41                          cleared
2026-08-11 14:08:29                                     cleared
2026-08-16 12:49:04 / 13:25:44                          cleared

2026-08-16 13:07:13  indexed: 0 entries (+0 new, 0.0 MB) in 1 ms
2026-08-16 13:26:59  indexed: 0 entries (+0 new, 0.0 MB) in 1 ms
```

**18 clears in nine days. Both index scans found 0 entries.** The L2 cache had
never once served a hit across a restart on this machine.

Worth noting how much work this was quietly wasting. The B3.12 benchmark in the
test suite, run today on real data:

```
B3.12 Disk Cache Benchmark (Instance_0000.dcm)
  Array: 910x1260 uint8
  Disk cache read:  0.00 ms
  pydicom decode:   3.41 ms
  Speedup:          341.3x
```

Also worth noting: the async-init work done earlier the same day made the
startup index scan free — but it was scanning an empty directory, so it saved
nothing real. That fix only becomes worth anything now.

## 3. The fix

A new method on the cache, and a one-word change at the call site.

```python
# disk_pixel_cache.py
def clear_on_exit(self) -> None:
    if (os.getenv("AIPACS_PIXEL_CACHE_CLEAR_ON_EXIT", "0") or "0").strip() == "1":
        self.clear()
        return
    ...
    logger.info("[B3.12] Disk pixel cache kept across shutdown: %d entries, "
                "%.1f MB (set AIPACS_PIXEL_CACHE_CLEAR_ON_EXIT=1 to wipe on exit)",
                entries, total_mb)
```

```python
# mainwindow_ui.py::_shutdown_caches
get_disk_pixel_cache().clear_on_exit()      # was: .clear()
```

Three deliberate choices:

- **A separate method, not a flag inside `clear()`.** An explicit,
  user-initiated "clear the cache" must always clear. Only the *shutdown
  policy* is configurable. `test_clear_source_does_not_consult_the_env_var`
  pins that seam so it cannot erode.
- **Only the disk cache changed.** The in-memory caches above it
  (`_thumbnail_cache`, `_metadata_cache`, `_image_cache`, `clear_study_cache()`)
  are still cleared unconditionally — they die with the process anyway.
- **It logs what it kept.** The next live run is verifiable from `app.log`
  alone, which is how every other change in this series was confirmed.

## 4. Why persistence is safe here

**It is bounded, not unbounded.** `_evict_if_needed()` runs on every write and
holds the cache under `_max_size_bytes` — **2 GB** by default
(`_DEFAULT_MAX_SIZE_MB = 2048`), evicting least-recently-used entries first.
The cache can never exceed the cap by more than one entry.

**The LRU order survives the restart.** `_scan_index()` restores the index
sorted by `st_mtime` ascending, and the OrderedDict's *order is* the eviction
order (`_evict_if_needed` pops from the front). Without that sort, the slice
the user viewed last before closing would become the first one evicted in the
next session — a cache working against itself.
`test_lru_order_survives_a_restart` pins exactly this.

**It cannot leak into version control.** `user_data/` is gitignored
(`.gitignore:55`), verified with `git check-ignore`.

## 5. What this costs

Be clear about the trade: the cache will now sit at up to **2 GB of decoded
patient pixel data on disk**, persistently, under
`user_data/cache/pixel_cache/`. Before this change it was transient — up to
2 GB during a session, zero between them. At the time of writing it holds
112 files / 1.6 MB, having been wiped at 13:25:44.

That data is **not new exposure in kind** — the source DICOM files already sit
unencrypted on the same disk under `SOURCE_PATH`, and the cache is a second
copy of the same images in a different format. But it is a change in
*duration*, and that is a site policy question, not a performance one.

**A shared or portable workstation should set
`AIPACS_PIXEL_CACHE_CLEAR_ON_EXIT=1`** and get the old behaviour back with no
code change.

## 6. A residual risk worth naming

The cache key is `_uid_hash(sop_instance_uid)` — a SHA-256 prefix of the SOP
Instance UID. SOP Instance UIDs are globally unique per image, so the same key
means the same pixels. The one way to get a *wrong* hit is a modality or
anonymiser that re-sends different pixel data under a UID it has already used —
a standards violation, but one that does happen in the field.

This risk already existed within a single session; persistence extends the
window to "until eviction". The mitigation already in the code is the
`expected_shape` check in `get()` / `_read_file()`, which rejects and deletes an
entry whose dimensions do not match — that catches the most likely
manifestation (a differently-sized re-send). A same-shape, different-pixels
re-send under a reused UID would not be caught. If that is ever observed,
adding the transfer-syntax UID (already named in the module docstring but not
actually part of the key today) or a content hash to the key is the fix.

## 7. Guard tests

`tests/code/viewer/test_disk_pixel_cache_persistence.py` — 20 tests.

| Group | What it pins |
|---|---|
| Persistence is the default | files survive `clear_on_exit()`; the *next* instance indexes them; a restored entry round-trips the exact pixels, not a stub |
| Kill switch works | `=1` wipes; 10 parametrised values confirm only a literal `1` (post-strip) wipes — `true`/`yes`/`on`/`2`/`01` all fall to the safe side |
| `clear()` stays unconditional | explicit clear wipes even with persistence on; AST check that `clear()` never reads the env var |
| Wiring | AST check that `_shutdown_caches` calls `clear_on_exit()` and **not** `clear()` |
| Still bounded | eviction under a lowered cap; evicted files really unlinked; LRU order survives a simulated restart and a just-read entry is not the one evicted |
| Shutdown-safe | `clear_on_exit()` swallows a failure in its own bookkeeping; it logs what it kept |

**Verified to fail on the pre-fix codebase**, per the catalog's rule that a
guard which cannot fail is decorative. With the call site reverted to `.clear()`
and `clear_on_exit()` forced to always wipe, **13 of the 20 fail**, including
both load-bearing ones (`test_cache_survives_shutdown_by_default`,
`test_shutdown_path_calls_clear_on_exit`). The 7 that still pass are the ones
that must hold in *both* modes — kill switch, explicit clear, never-raises, the
size cap.

## 8. Regression run

`pytest tests/code/viewer tests/code/fast` → **2373 passed, 28 skipped,
54 xfailed, 2 xpassed**, no failures. The xfails and xpasses are the
pre-existing quarantined set, unchanged by this work.

## 9. How to confirm it live

Restart the app twice and look in `user_data/logs/`. Expected on the way out:

```
[B3.12] Disk pixel cache kept across shutdown: N entries, M MB (...)
```

and on the way back in, the line that has read `0 entries` every time until
now:

```
[B3.12] Disk pixel cache indexed: N entries (+N new, M MB) in ... ms
```

A non-zero `N` on that second line is the whole fix.
