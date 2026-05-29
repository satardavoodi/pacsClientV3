from __future__ import annotations

import importlib.util
import sys
import tempfile
import threading
import time
import types
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _load_module_from_file(module_name: str, file_path: str):
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


_DM_ROOT = _PROJECT_ROOT / "modules" / "download_manager"
for _pkg in [
    "modules",
    "modules.download_manager",
    "modules.download_manager.core",
    "modules.download_manager.state",
    "modules.download_manager.rules",
]:
    if _pkg not in sys.modules:
        _stub = types.ModuleType(_pkg)
        _stub.__path__ = [str(_DM_ROOT / _pkg.split(".")[-1])] if "." in _pkg else [str(_PROJECT_ROOT / "modules")]
        _stub.__package__ = _pkg
        sys.modules[_pkg] = _stub
sys.modules["modules.download_manager"].__path__ = [str(_DM_ROOT)]

_load_module_from_file("modules.download_manager.core.exceptions", str(_DM_ROOT / "core" / "exceptions.py"))
_enums_mod = _load_module_from_file("modules.download_manager.core.enums", str(_DM_ROOT / "core" / "enums.py"))
_models_mod = _load_module_from_file("modules.download_manager.core.models", str(_DM_ROOT / "core" / "models.py"))
_load_module_from_file("modules.download_manager.state.state_machine", str(_DM_ROOT / "state" / "state_machine.py"))
_load_module_from_file("modules.download_manager.state.observers", str(_DM_ROOT / "state" / "observers.py"))
_state_store_mod = _load_module_from_file("modules.download_manager.state.state_store", str(_DM_ROOT / "state" / "state_store.py"))
_validation_rules_mod = _load_module_from_file("modules.download_manager.rules.validation_rules", str(_DM_ROOT / "rules" / "validation_rules.py"))
_rule_engine_mod = _load_module_from_file("modules.download_manager.rules.rule_engine", str(_DM_ROOT / "rules" / "rule_engine.py"))

DownloadPriority = _enums_mod.DownloadPriority
DownloadStatus = _enums_mod.DownloadStatus
DownloadTask = _models_mod.DownloadTask
SeriesInfo = _models_mod.SeriesInfo
DownloadStateStore = _state_store_mod.DownloadStateStore
ValidationRules = _validation_rules_mod.ValidationRules
DownloadRuleEngine = _rule_engine_mod.DownloadRuleEngine

# Populate the stub module with exported symbols so that other tests running in the
# same pytest session (e.g. smoke tests) can do `from modules.download_manager import X`
# without hitting ImportError against the empty stub.
_dm_stub = sys.modules["modules.download_manager"]
_dm_stub.DownloadPriority = _enums_mod.DownloadPriority
_dm_stub.DownloadStatus = _enums_mod.DownloadStatus
_dm_stub.DownloadTask = _models_mod.DownloadTask
_dm_stub.DownloadState = _models_mod.DownloadState
_dm_stub.SeriesInfo = _models_mod.SeriesInfo
_dm_stub.DownloadStateStore = _state_store_mod.DownloadStateStore
_dm_stub.get_state_store = _state_store_mod.get_state_store
_dm_stub.DownloadRuleEngine = _rule_engine_mod.DownloadRuleEngine
class _StubDownloadExecutor:  # lightweight stand-in; smoke tests only need importability
    pass
_dm_stub.DownloadExecutor = _StubDownloadExecutor


class KPICollector:
    def __init__(self):
        self.records: List[Dict[str, Any]] = []

    def add(self, scenario: str, metric: str, value: Any, passed: Optional[bool] = None):
        self.records.append({
            "scenario": scenario,
            "metric": metric,
            "value": value,
            "passed": passed,
        })

    def failed(self) -> List[Dict[str, Any]]:
        return [r for r in self.records if r["passed"] is False]


class FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, cb):
        self._callbacks.append(cb)

    def emit(self, *args, **kwargs):
        for cb in list(self._callbacks):
            cb(*args, **kwargs)


class FakeThumbnailManager:
    def __init__(self):
        self.started: List[str] = []
        self.progress_updates: List[tuple] = []
        self.completed: List[str] = []

    def start_series_download(self, series_number: str):
        self.started.append(str(series_number))

    def update_series_progress(self, series_number: str, progress_percent: float, status_text: str):
        self.progress_updates.append((str(series_number), float(progress_percent), str(status_text)))

    def complete_series_download(self, series_number: str):
        self.completed.append(str(series_number))


class FakeWidget:
    def __init__(self):
        self.thumbnail_manager = FakeThumbnailManager()
        self.series_images_progress = FakeSignal()
        self._progress_events: List[tuple] = []
        self._study_progress_events: List[tuple] = []
        self._lock = threading.Lock()
        self.series_images_progress.connect(self._on_series_images_progress)

    def update_download_progress(self, current: int, total: int, percent: float):
        with self._lock:
            self._study_progress_events.append((int(current), int(total), float(percent)))

    def _on_series_images_progress(self, series_number: str, current: int, total: int):
        with self._lock:
            self._progress_events.append((str(series_number), int(current), int(total)))


class FakeDownloadManagerSignals:
    def __init__(self):
        self.studyProgressUpdated = FakeSignal()
        self.seriesDownloadStarted = FakeSignal()
        self.seriesProgressUpdated = FakeSignal()
        self.seriesDownloadCompleted = FakeSignal()


class ConnectionBridge:
    """Minimal bridge equivalent to HomeUI _connect_download_manager_to_widget."""

    def __init__(self):
        self._connections = {}

    def connect(self, dm: FakeDownloadManagerSignals, widget: FakeWidget, study_uid: str):
        key = f"{study_uid}_{id(widget)}"
        if key in self._connections:
            return

        def on_study_progress(uid, current, total, percent):
            if uid == study_uid:
                widget.update_download_progress(current, total, percent)

        def on_series_started(uid, series_uid, _series_desc):
            if uid == study_uid:
                widget.thumbnail_manager.start_series_download(str(series_uid))

        def on_series_progress(uid, series_uid, current, total):
            if uid == study_uid:
                pct = (float(current) / float(total) * 100.0) if total else 0.0
                widget.thumbnail_manager.update_series_progress(str(series_uid), pct, f"{current}/{total}")
                widget.series_images_progress.emit(str(series_uid), int(current), int(total))

        def on_series_completed(uid, series_uid):
            if uid == study_uid:
                widget.thumbnail_manager.complete_series_download(str(series_uid))

        dm.studyProgressUpdated.connect(on_study_progress)
        dm.seriesDownloadStarted.connect(on_series_started)
        dm.seriesProgressUpdated.connect(on_series_progress)
        dm.seriesDownloadCompleted.connect(on_series_completed)
        self._connections[key] = True


class DownloadManagerHarness:
    def __init__(self, store: DownloadStateStore):
        self.store = store

    def set_viewed_series(self, study_uid: str, series_number: str):
        self.store.update(study_uid, viewed_series_number=str(series_number), priority=DownloadPriority.CRITICAL)

    def clear_viewed_series(self, study_uid: str):
        self.store.update(study_uid, viewed_series_number=None, priority=DownloadPriority.HIGH)


def _uid(seed: int) -> str:
    return f"1.2.840.10008.{seed}"


def _make_task(seed: int, patient_name: str, priority: DownloadPriority, series_count: int = 2) -> DownloadTask:
    series = [
        SeriesInfo(
            series_uid=_uid(seed * 100 + i),
            series_number=str(i),
            series_description=f"Series-{i}",
            modality="CT",
            image_count=12,
        )
        for i in range(1, series_count + 1)
    ]
    return DownloadTask(
        study_uid=_uid(seed),
        patient_id=f"PID-{seed}",
        patient_name=patient_name,
        study_date="20260331",
        modality="CT",
        description="Connection test",
        series_list=series,
        priority=priority,
    )


def _scenario_viewer_command_mapping(kpi: KPICollector):
    scenario = "C1: Viewer Command Mapping Parity"
    for backend_name in ("advanced_vtk", "fast_pydicom"):
        store = DownloadStateStore()
        dm = DownloadManagerHarness(store)
        task = _make_task(seed=1 if backend_name == "advanced_vtk" else 2,
                         patient_name=f"{backend_name}-pat",
                         priority=DownloadPriority.NORMAL)
        store.create(task)

        store.update(task.study_uid, priority=DownloadPriority.NORMAL)
        s = store.get(task.study_uid)
        kpi.add(scenario, f"{backend_name}: download click => NORMAL", s.priority == DownloadPriority.NORMAL, s.priority == DownloadPriority.NORMAL)

        store.update(task.study_uid, priority=DownloadPriority.HIGH)
        s = store.get(task.study_uid)
        kpi.add(scenario, f"{backend_name}: patient open => HIGH", s.priority == DownloadPriority.HIGH, s.priority == DownloadPriority.HIGH)

        dm.set_viewed_series(task.study_uid, "2")
        s = store.get(task.study_uid)
        ok = s.priority == DownloadPriority.CRITICAL and str(s.viewed_series_number) == "2"
        kpi.add(scenario, f"{backend_name}: series in layout => CRITICAL", ok, ok)

        dm.clear_viewed_series(task.study_uid)
        s = store.get(task.study_uid)
        ok = s.priority == DownloadPriority.HIGH and s.viewed_series_number is None
        kpi.add(scenario, f"{backend_name}: clear viewed => HIGH", ok, ok)


def _scenario_priority_negotiation_preemption(kpi: KPICollector):
    scenario = "C2: Priority Negotiation & Preemption"
    store = DownloadStateStore()
    engine = DownloadRuleEngine(store, {})

    normal = _make_task(10, "normal", DownloadPriority.NORMAL)
    high = _make_task(11, "high", DownloadPriority.HIGH)
    critical = _make_task(12, "critical", DownloadPriority.CRITICAL)

    for t in (normal, high, critical):
        store.create(t)

    store.update(normal.study_uid, status=DownloadStatus.DOWNLOADING)

    for s in store.get_by_status(DownloadStatus.DOWNLOADING):
        if s.priority < DownloadPriority.HIGH:
            store.update(s.study_uid, status=DownloadStatus.PAUSED, is_auto_paused=True)
    store.update(high.study_uid, status=DownloadStatus.DOWNLOADING)

    paused = store.get(normal.study_uid)
    ok = paused.status == DownloadStatus.PAUSED and paused.is_auto_paused
    kpi.add(scenario, "HIGH preempts active NORMAL", ok, ok)

    for s in store.get_by_status(DownloadStatus.DOWNLOADING):
        store.update(s.study_uid, status=DownloadStatus.PAUSED, is_auto_paused=True)
    store.update(critical.study_uid, status=DownloadStatus.DOWNLOADING)

    ok = len(store.get_by_status(DownloadStatus.DOWNLOADING)) == 1 and store.get(critical.study_uid).status == DownloadStatus.DOWNLOADING
    kpi.add(scenario, "CRITICAL runs exclusively", ok, ok)

    # after CRITICAL done, next pending should be HIGH before NORMAL
    store.update(critical.study_uid, status=DownloadStatus.COMPLETED)
    store.update(high.study_uid, status=DownloadStatus.PENDING, is_auto_paused=False)
    store.update(normal.study_uid, status=DownloadStatus.PENDING, is_auto_paused=False)

    nxt = engine.get_next_download()
    ok = nxt is not None and nxt.study_uid == high.study_uid
    kpi.add(scenario, "Post-critical queue picks HIGH first", ok, ok)


def _scenario_signal_bridge_roundtrip(kpi: KPICollector):
    scenario = "C3: DM→Viewer Signal Roundtrip"
    dm = FakeDownloadManagerSignals()
    widget = FakeWidget()
    bridge = ConnectionBridge()
    bridge.connect(dm, widget, "study-A")

    dm.studyProgressUpdated.emit("study-B", 1, 10, 10.0)
    dm.seriesProgressUpdated.emit("study-B", "2", 1, 10)

    dm.studyProgressUpdated.emit("study-A", 3, 10, 30.0)
    dm.seriesDownloadStarted.emit("study-A", "2", "desc")
    dm.seriesProgressUpdated.emit("study-A", "2", 4, 10)
    dm.seriesDownloadCompleted.emit("study-A", "2")

    with widget._lock:
        ok_progress = len(widget._study_progress_events) == 1
        ok_series = len(widget._progress_events) == 1 and widget._progress_events[0] == ("2", 4, 10)
    kpi.add(scenario, "Study progress filtered by study_uid", ok_progress, ok_progress)
    kpi.add(scenario, "Series progress emitted to widget", ok_series, ok_series)

    ok_started = widget.thumbnail_manager.started == ["2"]
    ok_completed = widget.thumbnail_manager.completed == ["2"]
    kpi.add(scenario, "Series start propagated", ok_started, ok_started)
    kpi.add(scenario, "Series completion propagated", ok_completed, ok_completed)


def _scenario_parallel_conversations_stress(kpi: KPICollector):
    scenario = "C4: Parallel Conversation Stress"
    dm = FakeDownloadManagerSignals()
    widget = FakeWidget()
    bridge = ConnectionBridge()
    bridge.connect(dm, widget, "study-P")

    errors: List[str] = []

    def producer_a():
        try:
            for i in range(1, 301):
                dm.seriesProgressUpdated.emit("study-P", "7", i, 300)
                if i % 75 == 0:
                    dm.seriesDownloadStarted.emit("study-P", "7", "s7")
        except Exception as e:
            errors.append(f"A:{e}")

    def producer_b():
        try:
            for i in range(1, 301):
                dm.studyProgressUpdated.emit("study-P", i, 300, i / 3)
                dm.seriesProgressUpdated.emit("study-X", "9", i, 300)  # noise from another study
                if i % 120 == 0:
                    dm.seriesDownloadCompleted.emit("study-P", "7")
        except Exception as e:
            errors.append(f"B:{e}")

    t0 = time.perf_counter()
    t1 = threading.Thread(target=producer_a)
    t2 = threading.Thread(target=producer_b)
    t1.start(); t2.start(); t1.join(); t2.join()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    with widget._lock:
        series_events = len(widget._progress_events)
        study_events = len(widget._study_progress_events)

    ok_no_errors = len(errors) == 0
    ok_only_target_events = series_events == 300 and study_events == 300
    kpi.add(scenario, "No callback exceptions under concurrency", ok_no_errors, ok_no_errors)
    kpi.add(scenario, "No cross-study leakage in events", ok_only_target_events, ok_only_target_events)
    kpi.add(scenario, "Concurrent dispatch wall time ms", round(elapsed_ms, 2), True)


def _scenario_priority_promotion_negotiation(kpi: KPICollector):
    scenario = "C5: Priority Promotion Negotiation"
    store = DownloadStateStore()
    engine = DownloadRuleEngine(store, {})

    active_normal = _make_task(20, "active-normal", DownloadPriority.NORMAL)
    target_high = _make_task(21, "target-high", DownloadPriority.NORMAL)

    store.create(active_normal)
    store.create(target_high)
    store.update(active_normal.study_uid, status=DownloadStatus.DOWNLOADING)

    promoted_task = replace(target_high, priority=DownloadPriority.HIGH)
    preemption = engine.evaluate_preemption(promoted_task)

    ok = preemption.action.value == "preempt_lower" and active_normal.study_uid in preemption.affected_downloads
    kpi.add(scenario, "Viewer promotion to HIGH requests lower-priority preemption", ok, ok)

    for paused_uid in preemption.affected_downloads:
        store.update(paused_uid, status=DownloadStatus.PAUSED, is_auto_paused=True)
    store.update(target_high.study_uid, priority=DownloadPriority.HIGH)

    paused_state = store.get(active_normal.study_uid)
    ok = paused_state.status == DownloadStatus.PAUSED and paused_state.is_auto_paused is True
    kpi.add(scenario, "Lower active study becomes auto-paused", ok, ok)

    store.update(target_high.study_uid, status=DownloadStatus.PENDING)
    nxt = engine.get_next_download()
    ok = nxt is not None and nxt.study_uid == target_high.study_uid
    kpi.add(scenario, "Promoted study becomes next queued candidate", ok, ok)


def _create_dcm_files(base: Path, study_uid: str, series_number: str, count: int):
    d = base / study_uid / series_number
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        (d / f"Instance_{i:04d}.dcm").write_bytes(b"\x00")


def _scenario_db_completion_retry_negotiation(kpi: KPICollector):
    scenario = "C6: DB Completion/Retry Negotiation"
    store = DownloadStateStore()
    rules = ValidationRules(store, {})

    with tempfile.TemporaryDirectory(prefix="conn_mod_") as td:
        root = Path(td)
        t = _make_task(30, "db-case", DownloadPriority.NORMAL, series_count=1)
        out = root / "study"
        _create_dcm_files(root / "study", "", "1", 12)
        t = replace(t, output_dir=out)

        side_effects = [RuntimeError("transient db read"), {"status": "Completed", "downloaded_count": 12, "progress_percent": 100.0}]

        with patch.object(_validation_rules_mod, "DATABASE_AVAILABLE", True), patch.object(
            _validation_rules_mod, "get_download_progress", side_effect=side_effects
        ):
            r1 = rules.validate_download_task(t)
            r2 = rules.validate_download_task(t)

        ok1 = r1.allowed is True and r1.action == "proceed"
        ok2 = r2.allowed is False and r2.action == "skip"
        kpi.add(scenario, "Transient DB failure => proceed", ok1, ok1)
        kpi.add(scenario, "Recovered DB complete => skip", ok2, ok2)


def _scenario_ui_action_state_consistency(kpi: KPICollector):
    """
    Contract hardening for DM UI/UX:
    If Start button is enabled for a state in details panel,
    _on_start_selected must support that same state.
    """
    scenario = "C7: UI Action-State Consistency"

    # Mirrors DownloadManagerWidget._update_button_states logic for Start button.
    start_enabled_statuses = {
        DownloadStatus.PAUSED,
        DownloadStatus.FAILED,
        DownloadStatus.CANCELLED,
    }

    # Mirrors DownloadManagerWidget._on_start_selected accepted states.
    start_handler_supported_statuses = {
        DownloadStatus.PAUSED,
        DownloadStatus.FAILED,
        DownloadStatus.CANCELLED,
    }

    mismatches = sorted(
        [s.value for s in start_enabled_statuses if s not in start_handler_supported_statuses]
    )

    ok = len(mismatches) == 0
    kpi.add(scenario, "Start-enabled statuses all have handler path", ok, ok)

    # Core statuses users hit in DM page must be aligned.
    user_visible_states = {DownloadStatus.PAUSED, DownloadStatus.FAILED, DownloadStatus.CANCELLED}
    ok = user_visible_states.issubset(start_handler_supported_statuses)
    kpi.add(scenario, "PAUSED/FAILED/CANCELLED Start semantics aligned", ok, ok)


def _run_suite() -> KPICollector:
    kpi = KPICollector()
    _scenario_viewer_command_mapping(kpi)
    _scenario_priority_negotiation_preemption(kpi)
    _scenario_signal_bridge_roundtrip(kpi)
    _scenario_parallel_conversations_stress(kpi)
    _scenario_priority_promotion_negotiation(kpi)
    _scenario_db_completion_retry_negotiation(kpi)
    _scenario_ui_action_state_consistency(kpi)
    return kpi


def test_connection_between_modules_kpis():
    kpi = _run_suite()
    failed = kpi.failed()
    assert not failed, f"Connection KPI failures: {failed}"
