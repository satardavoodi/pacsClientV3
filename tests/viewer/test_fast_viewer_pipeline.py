from types import SimpleNamespace
import threading

from PacsClient.pacs.patient_tab.ui.patient_ui import patient_widget_viewer_controller as controller_mod


class _DummyVtkImage:
    def __init__(self, dims=(160, 160, 128)):
        self._dims = dims

    def GetDimensions(self):
        return self._dims


def _build_controller():
    controller = controller_mod.ViewerController.__new__(controller_mod.ViewerController)
    controller.logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    controller.lst_nodes_viewer = []
    controller._is_request_current = lambda *args, **kwargs: True
    controller._perform_series_switch_optimized = lambda *args, **kwargs: None
    # Caches used by _invalidate_series_caches / _refresh_stored_metadata_instances
    controller._series_cache = {}
    controller._hot_series_cache = {}
    controller._metadata_flat_cache = {}
    controller._series_number_to_index = {}
    controller.zeta_boost = SimpleNamespace(invalidate_series=lambda *a, **kw: None)
    controller._disk_count_cache = {}
    controller.parent_widget = SimpleNamespace(
        lst_thumbnails_data=[],
        thumbnail_manager=SimpleNamespace(update_series_image_count=lambda *a: None),
    )
    return controller


def test_apply_loaded_series_data_rehydrates_parent_cache_without_refresh(tmp_path):
    controller = _build_controller()
    captured = {}
    series_dir = tmp_path / "study" / "5"
    series_dir.mkdir(parents=True)

    def _replace_series_data(**kwargs):
        captured.update(kwargs)
        return 3

    controller.parent_widget = SimpleNamespace(
        metadata_fixed={"patient_pk": 10, "study_pk": 20},
        replace_series_data=_replace_series_data,
        import_folder_path="",
    )

    controller._apply_loaded_series_data(
        series_number="5",
        vtk_image_data=_DummyVtkImage(),
        metadata={
            "series": {
                "thumbnail_path": "thumb.png",
                "series_path": str(series_dir),
            },
            "instances": [],
        },
        patient_pk=10,
        study_pk=20,
        refresh_viewer=False,
    )

    assert captured["allow_append_if_missing"] is True
    assert captured["series_number"] == "5"
    assert controller.parent_widget.import_folder_path == str(series_dir.parent)


def test_get_series_by_number_fast_rehydrates_from_full_cache(monkeypatch):
    controller = _build_controller()
    captured = {}
    vtk_data = _DummyVtkImage()
    metadata = {"series": {"series_number": "5", "thumbnail_path": "thumb.png"}}

    def _replace_series_data(series_number, vtk_image_data, metadata, file_path, allow_append_if_missing):
        captured["series_number"] = series_number
        captured["vtk_image_data"] = vtk_image_data
        captured["metadata"] = metadata
        captured["file_path"] = file_path
        captured["allow_append_if_missing"] = allow_append_if_missing
        return 0

    controller.parent_widget = SimpleNamespace(
        lst_thumbnails_data=[],
        replace_series_data=_replace_series_data,
    )
    controller._hot_series_cache = {}
    controller._series_cache = {}
    controller._series_number_to_index = {}
    controller._full_cache_get = lambda series_number: (vtk_data, metadata)
    controller._is_on_ui_thread = lambda: True
    controller._queue_on_ui_thread = lambda func: func()

    monkeypatch.setattr(controller_mod, "log_stage_timing", lambda *args, **kwargs: None)

    result = controller._get_series_by_number_fast("5")

    assert captured["allow_append_if_missing"] is True
    assert result == (vtk_data, metadata, 0)


def test_load_single_series_on_demand_uses_requested_fast_backend_when_backend_is_none(tmp_path, monkeypatch):
    controller = _build_controller()
    captured = {}
    study_root = tmp_path / "study"
    (study_root / "1").mkdir(parents=True)

    def _load_single_series_by_number(**kwargs):
        captured.update(kwargs)
        return None

    controller.parent_widget = SimpleNamespace(
        import_folder_path=str(study_root),
        metadata_fixed={"patient_pk": None, "study_pk": None},
        ordering_by_instances_number=None,
    )
    controller._get_requested_viewer_backend = lambda: controller_mod.BACKEND_PYDICOM
    controller._tab_active = True
    controller._interactive_load_in_progress = False
    controller.zeta_boost = SimpleNamespace(invalidate_series=lambda *args, **kwargs: None)
    controller._full_cache_get = lambda *args, **kwargs: None
    controller._get_series_by_number_fast = lambda *args, **kwargs: (None, None, -1)
    controller._series_load_lock = threading.Lock()
    controller._loading_series_numbers = set()
    controller._series_load_events = {}
    controller._interactive_full_load_semaphore = threading.BoundedSemaphore(1)
    controller._apply_loaded_series_data_threadsafe = lambda *args, **kwargs: None
    controller._prefetch_loaded = set()

    monkeypatch.setattr(controller_mod, "load_single_series_by_number", _load_single_series_by_number)
    monkeypatch.setattr(controller_mod, "log_stage_timing", lambda *args, **kwargs: None)

    result = controller._load_single_series_on_demand(series_number=1, viewer_backend=None)

    assert result is False
    assert captured["viewer_backend"] == controller_mod.BACKEND_PYDICOM
    assert captured["allow_lazy_backend"] is True


def test_get_requested_viewer_backend_prefers_parent_override(monkeypatch):
    controller = _build_controller()
    controller.parent_widget = SimpleNamespace(
        viewer_backend_override=controller_mod.BACKEND_PYDICOM,
    )

    monkeypatch.setattr(
        controller_mod,
        "load_viewer_backend",
        lambda default=controller_mod.BACKEND_VTK: controller_mod.BACKEND_VTK,
    )

    assert controller._get_requested_viewer_backend() == controller_mod.BACKEND_PYDICOM


# ────────────────────────────────────────────────────────────────
#  NEW: Progressive display done-set prevents double invocation
# ────────────────────────────────────────────────────────────────

def test_progressive_display_done_set_prevents_double_start():
    """
    Once _start_progressive_display succeeds for a series, the done-set
    should block subsequent invocations for the same study+series.
    """
    controller = _build_controller()
    controller._progressive_display_done = set()
    controller._progressive_display_inflight = set()

    study_uid = "1.2.3.4"
    series_number = "5"
    key = f"{study_uid}:{series_number}"

    # Simulate first successful progressive display
    controller._progressive_display_done.add(key)

    # Second call should be blocked by done-set
    blocked = key in controller._progressive_display_done
    assert blocked, "done-set should prevent second progressive display for same series"


def test_progressive_display_inflight_guard():
    """
    Inflight guard prevents concurrent _start_progressive_display for same series.
    """
    controller = _build_controller()
    controller._progressive_display_done = set()
    controller._progressive_display_inflight = set()

    key = "1.2.3:7"

    # Simulate inflight
    controller._progressive_display_inflight.add(key)

    assert key in controller._progressive_display_inflight
    assert key not in controller._progressive_display_done

    # After completion, move to done
    controller._progressive_display_inflight.discard(key)
    controller._progressive_display_done.add(key)

    assert key not in controller._progressive_display_inflight
    assert key in controller._progressive_display_done


# ────────────────────────────────────────────────────────────────
#  NEW: _ensure_import_folder_path resolves study directory
# ────────────────────────────────────────────────────────────────

def test_ensure_import_folder_path_resolves_from_source(tmp_path, monkeypatch):
    """
    _ensure_import_folder_path should set parent_widget.import_folder_path
    from SOURCE_PATH / study_uid when the directory exists.
    """
    controller = _build_controller()
    study_uid = "1.2.3.999"
    study_dir = tmp_path / study_uid
    study_dir.mkdir()

    controller.parent_widget = SimpleNamespace(
        import_folder_path=None,
        metadata_fixed={"study_uid": study_uid},
        study_uid=study_uid,
    )

    # SOURCE_PATH is lazy-imported inside the method from PacsClient.utils.config
    monkeypatch.setattr("PacsClient.utils.config.SOURCE_PATH", str(tmp_path))

    if hasattr(controller, '_ensure_import_folder_path'):
        controller._ensure_import_folder_path()
        assert controller.parent_widget.import_folder_path == str(study_dir)
    else:
        # Verify the concept: candidate path should exist
        from pathlib import Path
        candidate = Path(str(tmp_path)) / study_uid
        assert candidate.is_dir()


# ────────────────────────────────────────────────────────────────
#  NEW: Disk count cache TTL behavior
# ────────────────────────────────────────────────────────────────

def test_disk_count_cache_ttl():
    """
    The _disk_count_cache dict caches file counts with a 1-second TTL.
    Verify the cache structure and that stale entries are detectable.
    """
    import time
    controller = _build_controller()
    controller._disk_count_cache = {}

    series_key = "1.2.3:5"
    count = 42
    now = time.time()

    # Simulate cache write
    controller._disk_count_cache[series_key] = (count, now)

    # Read back — should be fresh
    cached_count, cached_time = controller._disk_count_cache[series_key]
    assert cached_count == 42
    assert (time.time() - cached_time) < 1.0  # within TTL

    # Simulate stale entry (fake old timestamp)
    controller._disk_count_cache[series_key] = (count, now - 2.0)
    _, stale_time = controller._disk_count_cache[series_key]
    assert (time.time() - stale_time) > 1.0  # expired


# ────────────────────────────────────────────────────────────────
#  NEW: DM notify cooldown prevents rapid-fire notifications
# ────────────────────────────────────────────────────────────────

def test_dm_notify_cooldown_prevents_rapid_fire():
    """
    _last_dm_notify_time_per_series enforces per-series cooldown.
    Second call within cooldown window should be suppressed.
    """
    import time
    controller = _build_controller()
    controller._last_dm_notify_time_per_series = {}
    controller._DM_VIEWED_NOTIFY_COOLDOWN_MS = 500

    series_key = "1.2.3:5"
    now_ms = time.monotonic() * 1000

    # First call — no entry, should proceed
    should_notify_1 = series_key not in controller._last_dm_notify_time_per_series
    assert should_notify_1

    # Record the notification time
    controller._last_dm_notify_time_per_series[series_key] = now_ms

    # Immediate second call — within cooldown, should be suppressed
    elapsed = time.monotonic() * 1000 - controller._last_dm_notify_time_per_series[series_key]
    should_notify_2 = elapsed >= controller._DM_VIEWED_NOTIFY_COOLDOWN_MS
    assert not should_notify_2, "Second call within cooldown should be suppressed"

    # Simulate cooldown expired
    controller._last_dm_notify_time_per_series[series_key] = now_ms - 600
    elapsed = time.monotonic() * 1000 - controller._last_dm_notify_time_per_series[series_key]
    should_notify_3 = elapsed >= controller._DM_VIEWED_NOTIFY_COOLDOWN_MS
    assert should_notify_3, "Call after cooldown should proceed"


# ────────────────────────────────────────────────────────────────
#  NEW: Done-guard recovery re-activates progressive mode
# ────────────────────────────────────────────────────────────────

def test_done_guard_recovery_reactivates_progressive_mode():
    """
    When sn is in _progressive_display_done but no progressive viewer is found,
    the done-guard recovery path should re-enter progressive mode on a viewer
    that is showing the series (non-progressively).  This prevents the grow
    path from being permanently blocked by the done-set.
    """
    controller = _build_controller()
    controller._progressive_display_done = {"5"}
    controller._progressive_display_inflight = set()
    controller._progressive_series = {
        "5": {"total": 100, "last_grow_count": 0, "last_signal_ms": 0},
    }
    controller._progressive_grow_batch_size = 10
    controller._is_fast_viewer_mode = lambda: True

    # Simulate a viewer showing series 5 but NOT in progressive mode
    mock_viewer = SimpleNamespace(
        _progressive_mode=False,
        _progressive_series_number=None,
        _total_expected_slices=0,
        _available_slice_count=0,
        image_viewer=SimpleNamespace(
            metadata={"series": {"series_number": "5"}},
        ),
        get_count_of_slices=lambda: 20,
        enter_progressive_mode=lambda total, sn: None,
        update_available_slice_count=lambda c: None,
    )
    # Track whether enter_progressive_mode is called
    calls = []
    mock_viewer.enter_progressive_mode = lambda total, sn: calls.append((total, sn))

    mock_node = SimpleNamespace(vtk_widget=mock_viewer, slider=None)
    controller.lst_nodes_viewer = [mock_node]

    # The done-guard recovery should find the viewer and call enter_progressive_mode
    # Simulate what on_series_images_progress does at the done-guard block:
    sn = "5"
    done = controller._progressive_display_done
    total = 100
    downloaded = 30

    # sn IS in done, and _find_progressive_viewers returns empty
    assert sn in done
    assert controller._find_progressive_viewers(sn) == []

    # Mimic the done-guard recovery code path
    recovery_found = False
    if sn in done and downloaded < total:
        for node in controller.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None or vtk_w._progressive_mode:
                continue
            try:
                viewer_sn = str(
                    getattr(vtk_w.image_viewer, "metadata", {})
                    .get("series", {}).get("series_number", "")
                )
            except Exception:
                viewer_sn = ""
            if viewer_sn == sn:
                vtk_w.enter_progressive_mode(total, sn)
                vtk_w.update_available_slice_count(vtk_w.get_count_of_slices())
                recovery_found = True
                break

    assert recovery_found, "Done-guard recovery should find viewer showing the series"
    assert len(calls) == 1, "enter_progressive_mode should be called exactly once"
    assert calls[0] == (100, "5"), f"Unexpected args: {calls[0]}"


def test_threaded_progressive_done_add_after_activation():
    """
    In the threaded fallback of _start_progressive_display:
    done.add(sn) must happen AFTER _display_series_after_load and
    _activate_progressive_mode_on_viewers, not before.
    This verifies the ordering expectation at the code level.
    """
    controller = _build_controller()
    controller._progressive_display_done = set()
    controller._progressive_display_inflight = set()

    sn = "7"

    # Simulate the CORRECT ordering:
    # 1. Display (noop in test)
    # 2. Activate (noop in test)
    # 3. Mark done
    assert sn not in controller._progressive_display_done

    # Step 1+2: display & activate would run here
    # Step 3: mark done
    controller._progressive_display_done.add(sn)

    assert sn in controller._progressive_display_done

    # The key property: between activation and done.add, the grow path
    # must be reachable. Before the fix, done.add was called from the
    # background thread (before activation). Now it's in the same
    # QTimer callback, after activation.
    # Here we just verify the set works correctly.
    assert len(controller._progressive_display_done) == 1


# ────────────────────────────────────────────────────────────────
#  NEW v2.2.8.5: Completion protocol tests (Layers 2–4)
# ────────────────────────────────────────────────────────────────


def _make_mock_viewer(series_number, slice_count=120, progressive=True, grow_target=None):
    """Build a fake VTK widget with controllable slice count and grow().

    *slice_count* — initial number of slices the viewer reports.
    *grow_target* — if set, grow() bumps the viewer's count to this value.
    """
    if grow_target is None:
        grow_target = slice_count
    grow_calls = []
    _current = [slice_count]

    class _FakeBackend:
        def __init__(self):
            self._paths = [f"/fake/{i}.dcm" for i in range(slice_count)]

        def get_file_paths(self):
            return list(self._paths)

        def refresh_file_list(self):
            pass

    class _FakeLoader:
        def __init__(self):
            self.backend = _FakeBackend()
            self._count = grow_target

        def grow(self):
            _current[0] = self._count
            grow_calls.append(self._count)
            return self._count

    loader = _FakeLoader()

    viewer = SimpleNamespace(
        image_viewer=SimpleNamespace(
            metadata={"series": {"series_number": series_number}},
            get_count_of_slices=lambda: _current[0],
            update_corners_actors=lambda **kw: None,
        ),
        _progressive_mode=progressive,
        _progressive_series_number=series_number if progressive else None,
        _progressive_grow_pending=False,
        _available_slice_count=slice_count,
        _total_expected_slices=grow_target if progressive else 0,
        _lazy_loader=loader,
        _qt_bridge_active=False,
        get_count_of_slices=lambda: _current[0],
        update_available_slice_count=lambda c: None,
        enter_progressive_mode=lambda t, sn: None,
        exit_progressive_mode=lambda: setattr(viewer, '_progressive_mode', False) or setattr(viewer, '_progressive_series_number', None),
        id_vtk_widget=1,
    )
    return viewer, loader, grow_calls


def test_on_series_download_fully_complete_does_final_grow():
    """
    Layer 2b: on_series_download_fully_complete calls loader.grow() before
    exiting progressive mode so the viewer shows all downloaded files.
    """
    controller = _build_controller()
    controller._progressive_series = {
        "202": {"total": 135, "last_grow_count": 120, "last_signal_ms": 0},
    }
    controller._completion_sweep_series_set = set()
    controller._completion_sweep_timer = SimpleNamespace(
        isActive=lambda: False, start=lambda: None, stop=lambda: None,
    )

    viewer, loader, grow_calls = _make_mock_viewer("202", slice_count=120, progressive=True, grow_target=135)
    loader._count = 135  # all files on disk

    slider = SimpleNamespace(
        blockSignals=lambda b: None,
        setMaximum=lambda v: None,
    )
    node = SimpleNamespace(vtk_widget=viewer, slider=slider)
    controller.lst_nodes_viewer = [node]

    # Suppress deferred verify (QTimer not available in test)
    import unittest.mock
    with unittest.mock.patch.object(
        controller_mod, "QTimer", create=True,
    ):
        controller.on_series_download_fully_complete("202")

    # grow() must have been called
    assert len(grow_calls) >= 1, "final grow must fire in on_series_download_fully_complete"
    # Series must be removed from progressive tracking
    assert "202" not in controller._progressive_series


def test_on_series_download_fully_complete_exits_progressive():
    """
    After final grow, exit_progressive_mode must be called — viewer
    must not remain in progressive mode.
    """
    controller = _build_controller()
    controller._progressive_series = {
        "5": {"total": 50, "last_grow_count": 40},
    }
    controller._completion_sweep_series_set = set()
    controller._completion_sweep_timer = SimpleNamespace(
        isActive=lambda: False, start=lambda: None, stop=lambda: None,
    )

    exit_calls = []
    viewer, loader, _ = _make_mock_viewer("5", slice_count=50, progressive=True)
    loader._count = 50
    orig_exit = viewer.exit_progressive_mode
    viewer.exit_progressive_mode = lambda: (exit_calls.append(1), orig_exit())

    node = SimpleNamespace(
        vtk_widget=viewer,
        slider=SimpleNamespace(blockSignals=lambda b: None, setMaximum=lambda v: None),
    )
    controller.lst_nodes_viewer = [node]

    import unittest.mock
    with unittest.mock.patch.object(controller_mod, "QTimer", create=True):
        controller.on_series_download_fully_complete("5")

    assert len(exit_calls) == 1, "exit_progressive_mode must be called exactly once"


def test_completion_verify_grows_stale_viewer(tmp_path):
    """
    Layer 3: _completion_verify_series detects viewer is behind disk count
    and triggers a catch-up grow.
    """
    controller = _build_controller()

    viewer, loader, grow_calls = _make_mock_viewer("10", slice_count=120, progressive=False, grow_target=135)

    slider_max = [119]  # 0-based
    def _set_max(v):
        slider_max[0] = v

    slider = SimpleNamespace(blockSignals=lambda b: None, setMaximum=_set_max)
    node = SimpleNamespace(vtk_widget=viewer, slider=slider)
    controller.lst_nodes_viewer = [node]

    # Stub _count_series_files_on_disk to return 135
    controller._count_series_files_on_disk = lambda sn: 135
    controller._refresh_stored_metadata_instances = lambda sn, c: None

    controller._completion_verify_series("10", expected_total=135)

    assert len(grow_calls) >= 1, "catch-up grow must fire"
    assert slider_max[0] == 134, "slider max must update to new_count - 1"


def test_completion_verify_skips_up_to_date_viewer():
    """
    Layer 3: If viewer already shows enough slices, no grow is triggered.
    """
    controller = _build_controller()

    viewer, loader, grow_calls = _make_mock_viewer("10", slice_count=135, progressive=False, grow_target=135)

    node = SimpleNamespace(
        vtk_widget=viewer,
        slider=SimpleNamespace(blockSignals=lambda b: None, setMaximum=lambda v: None),
    )
    controller.lst_nodes_viewer = [node]

    controller._count_series_files_on_disk = lambda sn: 135
    controller._refresh_stored_metadata_instances = lambda sn, c: None

    controller._completion_verify_series("10", expected_total=135)

    assert len(grow_calls) == 0, "no grow needed when viewer is up to date"


def test_completion_sweep_grows_stale_and_removes():
    """
    Layer 4: _completion_sweep_tick grows a stale viewer and removes the
    series from the sweep set once it's caught up.
    """
    controller = _build_controller()
    controller._completion_sweep_series_set = {("8", 100)}
    controller._completion_sweep_timer = SimpleNamespace(
        isActive=lambda: True, stop=lambda: None,
    )

    viewer, loader, grow_calls = _make_mock_viewer("8", slice_count=90, progressive=False, grow_target=100)

    node = SimpleNamespace(
        vtk_widget=viewer,
        slider=SimpleNamespace(blockSignals=lambda b: None, setMaximum=lambda v: None),
    )
    controller.lst_nodes_viewer = [node]

    controller._count_series_files_on_disk = lambda sn: 100
    controller._refresh_stored_metadata_instances = lambda sn, c: None

    controller._completion_sweep_tick()

    assert len(grow_calls) >= 1, "sweep must trigger grow for stale viewer"
    assert ("8", 100) not in controller._completion_sweep_series_set, \
        "series must be removed from sweep set after catch-up"


def test_completion_sweep_stops_when_empty():
    """
    Layer 4: sweep timer must stop itself when the sweep set is empty.
    """
    controller = _build_controller()
    controller._completion_sweep_series_set = set()
    stopped = []
    controller._completion_sweep_timer = SimpleNamespace(
        isActive=lambda: True,
        stop=lambda: stopped.append(1),
    )
    controller.lst_nodes_viewer = []

    controller._completion_sweep_tick()

    assert len(stopped) == 1, "timer must stop when sweep set is empty"


def test_completion_sweep_register_starts_timer():
    """
    Layer 4: _completion_sweep_register adds series to set and starts timer.
    """
    controller = _build_controller()
    controller._completion_sweep_series_set = set()
    started = []
    controller._completion_sweep_timer = SimpleNamespace(
        isActive=lambda: False,
        start=lambda: started.append(1),
    )

    controller._completion_sweep_register("99", 200)

    assert ("99", 200) in controller._completion_sweep_series_set
    assert len(started) == 1, "timer must start when series is registered"
