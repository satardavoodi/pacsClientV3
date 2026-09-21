"""Exercise real controller methods with synthetic payloads and a deterministic UI queue.

AST extraction omits module imports only; method bodies are executed unchanged.
No Qt/VTK construction, patient files, database, network, or application is used.
"""
from __future__ import annotations

import ast
import logging
import os
import subprocess
from pathlib import Path
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[3]
UI = ROOT / "PacsClient/pacs/patient_tab/ui/patient_ui"


def methods(filename, names, **extra):
    if os.environ.get("AIPACS_HANDOFF_TEST_BASELINE") == "1":
        # Reproduce against the verified clean pre-fix files without changing
        # the worktree. Only this test's selected methods are loaded from HEAD.
        source = subprocess.check_output(
            ["git", "show", "HEAD:" + (UI / filename).relative_to(ROOT).as_posix()], cwd=ROOT
        ).decode("utf-8-sig")
    else:
        source = (UI / filename).read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    nodes = [n for cls in tree.body if isinstance(cls, ast.ClassDef)
             for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    namespace = dict(os=os, time=time, threading=threading, Path=Path,
                     logger=logging.getLogger(__name__), BACKEND_VTK="vtk_simpleitk",
                     BACKEND_PYDICOM="pydicom_qt", VTKWidget=object, QSlider=object,
                     now_ms=lambda: 0, log_stage_timing=Mock(), _SERIESREF_DISK=False,
                     resolve_entry_study_location=lambda *a: (None, None))
    namespace.update(extra)
    code = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(code), str(UI / filename), "exec"), namespace)
    return namespace


@pytest.fixture
def state(tmp_path):
    parent = NS(metadata_fixed={"patient_pk": 1, "study_pk": 2, "synthetic": True},
                study_uid="synthetic-study", _server_series_info={}, import_folder_path=str(tmp_path),
                ordering_by_instances_number=False)
    s = NS(parent_widget=parent, logger=logging.getLogger(__name__), _tab_active=True,
           _interactive_load_in_progress=True, _loading_series_numbers=set(),
           _series_load_events={}, _series_load_lock=threading.Lock(), _prefetch_loaded=set(),
           _ensure_study_pk_for_db_metadata=Mock(), _resolve_plain_series_study_path=Mock(return_value=None),
           _resolve_series_ref=Mock(return_value=None), _log_seriesref_shadow=Mock(),
           _resolve_canonical_series_identity=Mock(return_value=("synthetic-study", "1", "synthetic-series")),
           _get_interactive_load_limits=Mock(return_value=(1, 1)),
           _requires_serialized_interactive_load=Mock(return_value=False),
           _is_request_current=Mock(return_value=True), _full_cache_put=Mock(),
           _full_cache_get=Mock(return_value=None), _get_series_by_number_fast=Mock(return_value=(None, None, -1)),
           _is_full_volume_cache_candidate=Mock(return_value=False), zeta_boost=Mock(),
           _apply_loaded_series_data_threadsafe=Mock(), _async_switch_inflight=set(),
           _set_zeta_external_interactive_busy=Mock(), _get_series_expected_slices=Mock(return_value=104),
           _should_use_interactive_preview=Mock(return_value=False), _get_viewer_id=lambda w: w.id_vtk_widget,
           _hide_spinner_for_widget=Mock(), _mark_first_series_displayed=Mock(),
           _coalesce_dm_view_intent=Mock(), _perform_series_switch_optimized=Mock(),
           _retire_load_cancellation=Mock(), _load_cancelled=lambda t: t.cancelled)
    s.token = NS(cancelled=False)
    s._register_load_cancellation = Mock(return_value=s.token)
    s.viewer = NS(id_vtk_widget=0, isVisible=Mock(return_value=True), last_series_show=0,
                  image_viewer=NS(metadata={"series": {"series_number": "1"}, "preview_only": True}),
                  get_count_of_slices=lambda: 8)
    s.lst_nodes_viewer = [NS(vtk_widget=s.viewer, slider=None)]
    s.payload = NS(GetDimensions=lambda: (4, 4, 104))
    s.metadata = {"series": {"series_number": "1"}, "instances": [{} for _ in range(104)]}
    s.ui = []
    s._queue_on_ui_thread = s.ui.append
    return s


@pytest.mark.parametrize("backend", ["vtk_simpleitk", "pydicom_qt"])
def test_full_result_after_hide_is_success_and_releases_ownership(state, backend):
    s = state
    events = []

    def loader(*a, **k):
        events.append(s._series_load_events["1"])
        s._tab_active = False
        return [(s.payload, s.metadata, (1, 2))]

    ns = methods("_vc_load.py", {"_load_single_series_on_demand"}, load_single_series_by_number=loader)
    ok = ns["_load_single_series_on_demand"](s, 1, s.parent_widget.import_folder_path,
        target_vtk_widget=s.viewer, expected_token=7, viewer_backend=backend, force_reload=True)
    assert ok is True, "a completed hidden-tab load is not a missing download"
    assert not s._loading_series_numbers and not s._series_load_events
    assert events[0].is_set()
    call = s._apply_loaded_series_data_threadsafe.call_args
    assert call.args[1] is s.payload and call.args[2] is s.metadata
    assert s.metadata["series"]["study_uid"] == "synthetic-study"


def test_visible_preview_does_not_short_circuit_full_load(state):
    loader = Mock(return_value=[(state.payload, state.metadata, (1, 2))])
    ns = methods("_vc_load.py", {"_load_single_series_on_demand"}, load_single_series_by_number=loader)
    assert ns["_load_single_series_on_demand"](state, 1, state.parent_widget.import_folder_path,
        target_vtk_widget=state.viewer, expected_token=7, viewer_backend="vtk_simpleitk")
    loader.assert_called_once()


def test_stale_after_decode_releases_owner_and_waiters(state):
    events = []

    def loader(*a, **k):
        events.append(state._series_load_events["1"])
        state._is_request_current.return_value = False
        return [(state.payload, state.metadata, (1, 2))]

    ns = methods("_vc_load.py", {"_load_single_series_on_demand"}, load_single_series_by_number=loader)
    assert ns["_load_single_series_on_demand"](state, 1, state.parent_widget.import_folder_path,
        target_vtk_widget=state.viewer, expected_token=7, viewer_backend="vtk_simpleitk", force_reload=True) is False
    assert not state._loading_series_numbers and not state._series_load_events
    assert events[0].is_set()
    state._apply_loaded_series_data_threadsafe.assert_not_called()


@pytest.mark.parametrize("active", [False, True])
def test_ui_publication_is_independent_of_render_visibility(state, active):
    s = state
    s._tab_active = active
    s.parent_widget.replace_series_data = Mock(return_value=0)
    s._is_viewer_fast_interacting = Mock(return_value=False)
    ns = methods("_vc_load.py", {"_apply_loaded_series_data"})
    ns["_apply_loaded_series_data"](s, 1, s.payload, s.metadata, 1, 2,
        refresh_viewer=True, target_viewer_id=0, expected_token=7)
    s.parent_widget.replace_series_data.assert_called_once()
    assert s._perform_series_switch_optimized.call_count == int(active)


def schedule(state, ok=True):
    s = state
    ns = methods("_vc_switch.py", {"_schedule_async_load_and_switch", "_replay_deferred_interactive_completions"},
        threading=NS(Thread=lambda target, **kw: NS(start=target)),
        QTimer=NS(singleShot=lambda ms, cb: s.ui.append(cb)))
    if "_replay_deferred_interactive_completions" in ns:
        s._replay_deferred_interactive_completions = lambda: ns["_replay_deferred_interactive_completions"](s)
    s._load_single_series_on_demand = Mock(return_value=ok)
    s._get_series_by_number_fast.return_value = (s.payload, s.metadata, 0)
    ns["_schedule_async_load_and_switch"](s, "1", s.parent_widget.import_folder_path,
        s.viewer, None, False, 7, s.viewer, time.perf_counter())
    s.ui.pop(0)()


def test_hidden_finish_waits_for_activation_without_download_or_render(state):
    s = state
    s._tab_active = False
    schedule(s)
    s._perform_series_switch_optimized.assert_not_called()
    s._coalesce_dm_view_intent.assert_not_called()
    assert not s._async_switch_inflight and not s._interactive_load_in_progress
    assert len(s._deferred_interactive_completions) == 1
    s._tab_active = True
    s._replay_deferred_interactive_completions()
    while s.ui:
        s.ui.pop(0)()
    s._perform_series_switch_optimized.assert_called_once()
    assert not s._deferred_interactive_completions


@pytest.mark.parametrize("stale", ["token", "cancelled", "deleted"])
def test_deferred_finish_does_not_touch_retired_target(state, stale):
    s = state
    s._tab_active = False
    schedule(s)
    s._perform_series_switch_optimized.assert_not_called()
    s._tab_active = True
    if stale == "token":
        s._is_request_current.return_value = False
    elif stale == "cancelled":
        s.token.cancelled = True
        s.viewer.isVisible.reset_mock()
    else:
        s.viewer.isVisible.side_effect = RuntimeError("deleted synthetic widget")
    s._replay_deferred_interactive_completions()
    while s.ui:
        s.ui.pop(0)()
    s._perform_series_switch_optimized.assert_not_called()
    s._coalesce_dm_view_intent.assert_not_called()
    if stale == "cancelled":
        s.viewer.isVisible.assert_not_called()


def test_activation_rehide_keeps_completion_for_next_activation(state):
    s = state
    s._tab_active = False
    schedule(s)
    s._perform_series_switch_optimized.assert_not_called()
    s._tab_active = True
    s._replay_deferred_interactive_completions()
    s._tab_active = False
    s.ui.pop(0)()
    assert len(s._deferred_interactive_completions) == 1
    s._tab_active = True
    s._replay_deferred_interactive_completions()
    s.ui.pop(0)()
    s._perform_series_switch_optimized.assert_called_once()


@pytest.mark.parametrize("boost", [False, True])
def test_activation_replays_explicit_completion_in_manual_and_auto_mode(state, boost):
    s = state
    s._is_boostviewer_enabled_runtime = lambda: boost
    s._replay_deferred_interactive_completions = Mock()
    s._replay_deferred_series_loads_after_activation = Mock()
    s._schedule_activation_study_check = Mock()
    ns = methods("_vc_cache.py", {"on_tab_activated"}, QTimer=NS(singleShot=Mock()))
    ns["on_tab_activated"](s)
    s._replay_deferred_interactive_completions.assert_called_once()


@pytest.mark.parametrize("retired", ["closed", "missing_target", "stale"])
def test_retired_ui_result_cannot_mutate_catalog(state, retired):
    s = state
    s.parent_widget.replace_series_data = Mock(return_value=0)
    if retired == "closed":
        s._viewer_loads_closed = True
    elif retired == "missing_target":
        s.lst_nodes_viewer.clear()
    else:
        s._is_request_current.return_value = False
    ns = methods("_vc_load.py", {"_apply_loaded_series_data"})
    ns["_apply_loaded_series_data"](s, 1, s.payload, s.metadata, 1, 2,
        refresh_viewer=True, target_viewer_id=0, expected_token=7)
    s.parent_widget.replace_series_data.assert_not_called()
    s._perform_series_switch_optimized.assert_not_called()


def test_close_clears_deferred_callbacks_and_late_apply_guard(state):
    s = state
    s._tab_active = False
    schedule(s)
    ns = methods("_vc_switch.py", {"cancel_inflight_loads"})
    s._cancel_registry = NS(cancel_all=Mock(return_value=1))
    assert ns["cancel_inflight_loads"](s) == 1
    assert s._viewer_loads_closed and not s._deferred_interactive_completions


@pytest.mark.parametrize("active", [False, True])
def test_genuine_missing_files_keep_download_wait_semantics(state, active):
    s = state
    s._tab_active = active
    s._log_viewport_lifecycle = Mock()
    schedule(s, ok=False)
    assert s._coalesce_dm_view_intent.call_count == int(active)
    s._perform_series_switch_optimized.assert_not_called()
    if not active:
        s._tab_active = True
        s._replay_deferred_interactive_completions()
        s.ui.pop(0)()
    s._coalesce_dm_view_intent.assert_called_once_with("1", want_trigger=True)
    assert s.viewer._awaiting_series_number == "1"


@pytest.mark.parametrize("backend", ["vtk_simpleitk", "pydicom_qt"])
def test_complete_worker_to_ui_handoff_survives_tab_switch(state, backend):
    """The real load, queued publication, finish, and activation methods compose."""
    s = state
    catalog = {}

    def replace(**kwargs):
        catalog[str(kwargs["series_number"])] = (kwargs["vtk_image_data"], kwargs["metadata"], 0)
        return 0

    def loader(*a, **k):
        s._tab_active = False  # User leaves while the background load finishes.
        return [(s.payload, s.metadata, (1, 2))]

    load_ns = methods("_vc_load.py", {"_load_single_series_on_demand", "_apply_loaded_series_data",
                                      "_apply_loaded_series_data_threadsafe"},
                      load_single_series_by_number=loader)
    for name in ("_load_single_series_on_demand", "_apply_loaded_series_data",
                 "_apply_loaded_series_data_threadsafe"):
        setattr(s, name, load_ns[name].__get__(s))
    s._is_on_ui_thread = lambda: False
    s.parent_widget.replace_series_data = replace
    s._get_series_by_number_fast = lambda key: catalog.get(key, (None, None, -1))
    s._is_viewer_fast_interacting = lambda w: False
    switch_ns = methods("_vc_switch.py", {"_schedule_async_load_and_switch", "_replay_deferred_interactive_completions"},
        threading=NS(Thread=lambda target, **kw: NS(start=target)), QTimer=NS(singleShot=lambda ms, cb: s.ui.append(cb)))
    switch_ns["_schedule_async_load_and_switch"](s, "1", s.parent_widget.import_folder_path,
        s.viewer, None, False, 7, s.viewer, time.perf_counter(), viewer_backend=backend, force_reload=True)
    while s.ui:
        s.ui.pop(0)()
    assert catalog["1"][:2] == (s.payload, s.metadata)
    assert not s._loading_series_numbers
    s._perform_series_switch_optimized.assert_not_called()
    s._coalesce_dm_view_intent.assert_not_called()
    s._tab_active = True
    switch_ns["_replay_deferred_interactive_completions"](s)
    while s.ui:
        s.ui.pop(0)()
    call = s._perform_series_switch_optimized.call_args
    assert call.args[0] is s.viewer and call.args[1] is s.metadata and call.args[2] is s.payload
    assert len(call.args[1]["instances"]) == call.args[2].GetDimensions()[2] == 104
    s._perform_series_switch_optimized.assert_called_once()
    s._coalesce_dm_view_intent.assert_not_called()


def test_secondary_study_hidden_result_keeps_display_key_and_own_identity(state):
    s = state
    s.parent_widget._server_series_info = {"1000001": {"study_uid": "synthetic-secondary"}}
    s._ms_study_pk_cache = {"synthetic-secondary": 3}
    s._resolve_canonical_series_identity.return_value = ("synthetic-secondary", "1", "synthetic-series-B")

    def loader(*a, **k):
        assert k["series_number"] == 1 and k["study_pk"] == 3
        s._tab_active = False
        return [(s.payload, s.metadata, (1, 3))]

    ns = methods("_vc_load.py", {"_load_single_series_on_demand"}, load_single_series_by_number=loader,
                 resolve_entry_study_location=lambda *a: (s.parent_widget.import_folder_path, 1))
    assert ns["_load_single_series_on_demand"](s, 1000001, s.parent_widget.import_folder_path,
        target_vtk_widget=s.viewer, expected_token=7, viewer_backend="pydicom_qt", force_reload=True)
    series = s.metadata["series"]
    assert series["series_number"] == "1000001" and series["_orig_series_number"] == "1"
    assert series["study_uid"] == "synthetic-secondary" and series["series_uid"] == "synthetic-series-B"


def test_closed_controller_cannot_start_another_async_load(state):
    state._viewer_loads_closed = True
    thread = Mock()
    ns = methods("_vc_switch.py", {"_schedule_async_load_and_switch"}, threading=NS(Thread=thread))
    ns["_schedule_async_load_and_switch"](state, "1", state.parent_widget.import_folder_path,
        state.viewer, None, False, 7, state.viewer, time.perf_counter())
    thread.assert_not_called()
    assert not state._async_switch_inflight


def test_complete_resident_pair_still_skips_decoding(state):
    state._get_series_by_number_fast.return_value = (state.payload, state.metadata, 0)
    state._is_full_volume_cache_candidate.return_value = True
    loader = Mock()
    ns = methods("_vc_load.py", {"_load_single_series_on_demand"}, load_single_series_by_number=loader)
    assert ns["_load_single_series_on_demand"](state, 1, state.parent_widget.import_folder_path,
        target_vtk_widget=state.viewer, expected_token=7, viewer_backend="vtk_simpleitk")
    loader.assert_not_called()


def test_deferred_completion_replaces_old_full_same_series_view(state):
    state.viewer.image_viewer.metadata = {
        "series": {"series_number": "1"}, "instances": [{} for _ in range(104)]}
    state._tab_active = False
    schedule(state)
    state._tab_active = True
    state._replay_deferred_interactive_completions()
    state.ui.pop(0)()
    state._perform_series_switch_optimized.assert_called_once()
    assert state._perform_series_switch_optimized.call_args.args[1] is state.metadata
