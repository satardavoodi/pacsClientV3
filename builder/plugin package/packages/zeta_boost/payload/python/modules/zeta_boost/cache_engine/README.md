# cache_engine — ZetaBoostEngine Split (Phase 4)

Extracted from the monolithic `engine.py` (1,187 lines, 52 methods)
into focused mixin files under `modules/zeta_boost/cache_engine/`.

## Files

| File | Class / Purpose | Methods | Lines |
|------|----------------|---------|-------|
| `_zb_globals.py` | Module-level globals & utilities (`_GLOBAL_DOWNLOAD_ACTIVE`, `set_global_download_active`, `_set_thread_low_priority`) | 2 funcs | ~50 |
| `_zb_cache.py` | `_ZBCacheMixin` — Cache ops: query, get, put, trim, clear, evict, invalidate | 10 | ~330 |
| `_zb_lanes.py` | `_ZBLanesMixin` — Lane management: normalize, enqueue, clear pending | 14 | ~213 |
| `_zb_workers.py` | `_ZBWorkersMixin` — Worker loop, disk promotion, memory check, failsafe | 6 | ~238 |
| `_zb_lifecycle.py` | `_ZBLifecycleMixin` — Lifecycle, state, health, global lock, boost mode | 21 | ~272 |
| `widget.py` | `ZetaBoostEngine` — Core class with `__init__`, class attrs, mixin assembly | 1 | ~130 |
| `__init__.py` | Re-exports `ZetaBoostEngine`, `set_global_download_active`, `_set_thread_low_priority` | — | 4 |

## Backward Compatibility

The original `modules/zeta_boost/engine.py` is now a thin shim that re-exports
all public names from `cache_engine/`. Existing imports like:

```python
from modules.zeta_boost.engine import ZetaBoostEngine
from modules.zeta_boost.engine import set_global_download_active
```

continue to work unchanged.

## Design Notes

- `_zb_globals.py` exists to avoid circular imports: `widget.py` imports mixins,
  and `_zb_workers.py` needs runtime access to the mutable `_GLOBAL_DOWNLOAD_ACTIVE`
  flag. Workers import the `_zb_globals` module and read the attribute at runtime
  (`_zb_globals._GLOBAL_DOWNLOAD_ACTIVE`) to always see the current value.

- `_RAM_CHECK_INTERVAL_SEC` and `_RAM_MIN_AVAIL_MB` class attributes are in
  `_zb_workers.py` alongside `_check_system_memory_ok` which uses them.

## Created

Phase 4 of the large-file refactoring plan, 2026-04-09.
