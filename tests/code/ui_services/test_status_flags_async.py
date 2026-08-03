"""Per-row Status flags computed OFF the GUI thread (2026-08-02).

Root cause of a multi-second freeze when the local patient list rendered (e.g.
right after importing a study): `_build_local_status_widget` called
`_compute_local_status_flags` per row on the GUI thread — an `os.walk` of the
study's attachments folder + a reception-payload file read + several DB queries.
Now the row renders immediately (cache hit, or an empty placeholder on a miss)
and the flags are computed on a background worker, delivered to the GUI thread
via the `statusFlagsReady` signal with a generation guard.

`patient_table_widget.py` imports Qt at module scope, so this is source-pinned.
"""
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found")


def _src() -> str:
    return (_repo_root() / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
            / "patient_table_widget.py").read_text(encoding="utf-8")


def _method(src: str, name: str) -> str:
    i = src.find(f"def {name}(")
    assert i != -1, f"method {name} not found"
    body = src[i:]
    nxt = body.find("\n    def ", 10)
    return body[:nxt] if nxt != -1 else body


def test_async_signal_and_flag_default_on():
    src = _src()
    assert "statusFlagsReady = Signal(str, str, object, int)" in src
    assert 'os.getenv("AIPACS_STATUS_ASYNC", "1")' in src
    # default on: absent env resolves truthy
    fn = _method(src, "_status_async_enabled")
    assert '!= "0"' in fn


def test_build_widget_async_is_opt_in_and_cache_only():
    src = _src()
    fn = _method(src, "_build_local_status_widget")
    # async is OPT-IN (bulk render only) AND gated by the flag
    assert "allow_async: bool = False" in fn
    assert "_async = bool(allow_async) and self._status_async_enabled()" in fn
    # async mode reads the cache ONLY (never computes on the GUI thread)
    assert "self._get_cached_status_flags(s_uid, p_id) if _async else None" in fn
    # a miss in async mode renders empty + defers to a worker
    assert "_deferred = True" in fn
    assert "self._dispatch_status_flags_async(s_uid, p_id, container)" in fn
    # NON-async callers still compute synchronously (legacy contract preserved,
    # so container.status_flags is populated on return for refresh/tests)
    assert "flags = self._compute_local_status_flags(s_uid, p_id)" in fn


def test_only_the_bulk_render_opts_into_async():
    src = _src()
    # add_patient_data (the per-row render that froze the list) opts in;
    # the default False keeps every other caller synchronous.
    fn = _method(src, "add_patient_data")
    assert "self._build_local_status_widget(study_uid, patient_id, allow_async=True)" in fn


def test_cache_only_read_never_computes():
    src = _src()
    fn = _method(src, "_get_cached_status_flags")
    # returns None on a miss (caller falls back to async compute)
    assert "return None" in fn
    # MUST NOT trigger the expensive compute — that is the whole point
    assert "_compute_local_status_flags" not in fn
    assert "_local_status_cache.get(key)" in fn


def test_worker_computes_offthread_and_emits():
    src = _src()
    fn = _method(src, "_dispatch_status_flags_async")
    assert "self._status_pool.submit(_work)" in fn
    assert "self._compute_local_status_flags(su, pi)" in fn   # runs on the worker
    assert "self.statusFlagsReady.emit(" in fn
    # the pool is a real background thread pool
    assert "ThreadPoolExecutor" in _method(src, "_ensure_status_async")


def test_result_slot_has_generation_guard_and_is_delete_safe():
    src = _src()
    fn = _method(src, "_on_status_flags_ready")
    assert "if gen != getattr(self, '_status_async_gen', 0):" in fn
    assert "self._pending_status_containers.pop(" in fn
    assert "except RuntimeError:" in fn      # container/row deleted → benign
    assert "self._populate_status_chips(lay, flags)" in fn


def test_clear_table_bumps_generation():
    src = _src()
    fn = _method(src, "clear_table")
    assert "self._status_async_gen = getattr(self, '_status_async_gen', 0) + 1" in fn
    assert "self._pending_status_containers.clear()" in fn


def test_populate_chips_is_idempotent():
    src = _src()
    fn = _method(src, "_populate_status_chips")
    # clears existing chips before rebuilding (so the async fill is safe)
    assert "layout.takeAt(0)" in fn
    assert "deleteLater()" in fn
    assert "_chip(" in fn  # still builds the chips
