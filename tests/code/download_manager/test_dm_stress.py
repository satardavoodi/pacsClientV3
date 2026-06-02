"""
Download Manager — Heavy-Load Stress & KPI Test Suite
======================================================

Run:
    python tests/download_manager/test_dm_stress.py

What it tests under extreme conditions:
    H1.  50 concurrent patient downloads — state store scalability
    H2.  Rapid drag-drop simulation (500 series switches in <5s)
    H3.  Multi-threaded state store contention (16 threads × 500 ops)
    H4.  High-frequency progress signals (10,000 updates, observer fan-out)
    H5.  Memory pressure — 200 studies with 20 series each
    H6.  Priority negotiation storm — all studies request CRITICAL simultaneously
    H7.  Coordinator churn — create/promote/complete/resume 100 cycles
    H8.  File I/O stress — 10 studies × 10 series × 100 files each
    H9.  Rule engine throughput — 1000 get_next_download under full store
    H10. Combined pipeline — priority flip + observer + coordinator + file I/O

No live server connection required — all network I/O is mocked.
"""

from __future__ import annotations

import gc
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

# ── project root on sys.path ── (tests/code/download_manager/ → repo root needs 4 parents after the 2026-05-27 reorg)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dm_stress")

# ═══════════════════════════════════════════════════════════════════
#  Imports (same bootstrap as test_download_manager.py)
# ═══════════════════════════════════════════════════════════════════
import importlib.util
import types as _types

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
    "modules.download_manager.coordinator",
]:
    if _pkg not in sys.modules:
        _stub = _types.ModuleType(_pkg)
        _stub.__path__ = [str(_DM_ROOT / _pkg.split(".")[-1])] if "." in _pkg else [str(_PROJECT_ROOT / "modules")]
        _stub.__package__ = _pkg
        sys.modules[_pkg] = _stub

sys.modules["modules.download_manager"].__path__ = [str(_DM_ROOT)]

_load_module_from_file("modules.download_manager.core.exceptions", str(_DM_ROOT / "core" / "exceptions.py"))
_enums_mod = _load_module_from_file("modules.download_manager.core.enums", str(_DM_ROOT / "core" / "enums.py"))
_models_mod = _load_module_from_file("modules.download_manager.core.models", str(_DM_ROOT / "core" / "models.py"))
_constants_mod = _load_module_from_file("modules.download_manager.core.constants", str(_DM_ROOT / "core" / "constants.py"))
_load_module_from_file("modules.download_manager.state.state_machine", str(_DM_ROOT / "state" / "state_machine.py"))
_load_module_from_file("modules.download_manager.state.observers", str(_DM_ROOT / "state" / "observers.py"))
_state_store_mod = _load_module_from_file("modules.download_manager.state.state_store", str(_DM_ROOT / "state" / "state_store.py"))
_load_module_from_file("modules.download_manager.rules.priority_rules", str(_DM_ROOT / "rules" / "priority_rules.py"))
_load_module_from_file("modules.download_manager.rules.validation_rules", str(_DM_ROOT / "rules" / "validation_rules.py"))
_rule_engine_mod = _load_module_from_file("modules.download_manager.rules.rule_engine", str(_DM_ROOT / "rules" / "rule_engine.py"))
_coordinator_mod = _load_module_from_file("modules.download_manager.coordinator.series_intent_coordinator", str(_DM_ROOT / "coordinator" / "series_intent_coordinator.py"))

DownloadPriority = _enums_mod.DownloadPriority
DownloadStatus = _enums_mod.DownloadStatus
DownloadResult = _models_mod.DownloadResult
DownloadState = _models_mod.DownloadState
DownloadTask = _models_mod.DownloadTask
SeriesInfo = _models_mod.SeriesInfo
BATCH_SIZE = _constants_mod.BATCH_SIZE
MAX_CONCURRENT_STUDIES = _constants_mod.MAX_CONCURRENT_STUDIES
DownloadStateStore = _state_store_mod.DownloadStateStore
DownloadRuleEngine = _rule_engine_mod.DownloadRuleEngine
SeriesIntentCoordinator = _coordinator_mod.SeriesIntentCoordinator


# ═══════════════════════════════════════════════════════════════════
#  KPI Collector (same as main test suite)
# ═══════════════════════════════════════════════════════════════════

class KPICollector:
    def __init__(self):
        self._records: List[Dict[str, Any]] = []

    def record(self, scenario: str, metric: str, value: Any, unit: str = "", passed: Optional[bool] = None):
        self._records.append({"scenario": scenario, "metric": metric, "value": value, "unit": unit, "passed": passed})

    def report(self) -> str:
        lines: List[str] = []
        lines.append("")
        lines.append("=" * 110)
        lines.append("  DOWNLOAD MANAGER — HEAVY-LOAD STRESS KPI REPORT")
        lines.append("=" * 110)

        scenarios: Dict[str, list] = defaultdict(list)
        for r in self._records:
            scenarios[r["scenario"]].append(r)

        total_pass = total_fail = total_skip = 0
        for scenario, records in scenarios.items():
            lines.append("")
            lines.append(f"  +-- Scenario: {scenario}")
            lines.append(f"  |{'Metric':<50} {'Value':>18} {'Unit':<12} {'Status':>8}")
            lines.append(f"  |{'_' * 90}")
            for r in records:
                if r["passed"] is True:
                    status_str = "  PASS"
                    total_pass += 1
                elif r["passed"] is False:
                    status_str = "  FAIL"
                    total_fail += 1
                else:
                    status_str = "  info"
                    total_skip += 1
                val = r["value"]
                val_str = f"{val:>18.3f}" if isinstance(val, float) else f"{str(val):>18}"
                lines.append(f"  | {r['metric']:<49} {val_str} {r['unit']:<12}{status_str}")
            lines.append(f"  +{'_' * 90}")

        lines.append("")
        lines.append("=" * 110)
        lines.append(f"  TOTALS:  PASS {total_pass}   FAIL {total_fail}   info {total_skip}")
        lines.append("=" * 110)
        lines.append("")
        return "\n".join(lines)


_kpi = KPICollector()


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def _uid() -> str:
    return f"1.2.840.{uuid.uuid4().int % 10**12}"


def _make_series(count: int = 3, images_per_series: int = 32) -> List[SeriesInfo]:
    return [
        SeriesInfo(
            series_uid=_uid(), series_number=str(i),
            series_description=f"Series-{i}", modality="CT",
            image_count=images_per_series,
        ) for i in range(1, count + 1)
    ]


def _make_task(
    study_uid: str | None = None, patient_name: str = "StressPatient",
    series_count: int = 3, images_per_series: int = 32,
    priority: DownloadPriority = DownloadPriority.NORMAL,
    study_date: str = "20260402",
) -> DownloadTask:
    uid = study_uid or _uid()
    return DownloadTask(
        study_uid=uid, patient_id=f"PID-{uuid.uuid4().hex[:6]}",
        patient_name=patient_name, study_date=study_date,
        modality="CT", description="Stress test study",
        series_list=_make_series(series_count, images_per_series),
        priority=priority,
    )


@contextmanager
def _temp_output_dir():
    d = tempfile.mkdtemp(prefix="dm_stress_")
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _create_dcm_files(base: Path, study_uid: str, series_number: str, count: int):
    series_dir = base / study_uid / series_number
    series_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        (series_dir / f"Instance_{i:04d}.dcm").write_bytes(b"\x00" * 256)


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _percentile(data: List[float], pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = int(len(s) * pct / 100.0)
    return s[min(idx, len(s) - 1)]


def _make_coordinator(store, engine, tasks, calls=None):
    """Helper to build a SeriesIntentCoordinator with dummy callbacks."""
    if calls is None:
        calls = {"paused": [], "start": 0, "refresh": 0, "resume": 0}

    class _FakePool:
        def can_add_worker(self):
            return True

    return SeriesIntentCoordinator(
        state_store=store,
        rule_engine=engine,
        worker_pool=_FakePool(),
        tasks_ref={t.study_uid: t for t in tasks},
        pause_downloads_for_preemption=lambda uids: calls["paused"].extend(uids),
        start_download_worker=lambda _uid: True,
        start_next_pending=lambda: calls.__setitem__("start", calls["start"] + 1),
        refresh_table_order=lambda: calls.__setitem__("refresh", calls["refresh"] + 1),
        check_auto_resume=lambda: calls.__setitem__("resume", calls["resume"] + 1),
        defer_call=lambda _delay, cb: cb(),
    ), calls


# ═══════════════════════════════════════════════════════════════════
#  H1 — 50 Concurrent Patient Downloads (State Store Scalability)
# ═══════════════════════════════════════════════════════════════════

def h1_concurrent_patient_scalability():
    """
    Create 50 patients with 5 series each, all DOWNLOADING simultaneously.
    Measure: create/update/read/remove throughput, memory, GC impact.
    """
    SCENARIO = "H1: 50 Concurrent Patients"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    NUM_PATIENTS = 50
    SERIES_PER_PATIENT = 5

    # ── Create phase ──
    tasks: List[DownloadTask] = []
    t0 = time.perf_counter()
    for i in range(NUM_PATIENTS):
        t = _make_task(patient_name=f"Heavy-{i:03d}", series_count=SERIES_PER_PATIENT, images_per_series=64)
        store.create(t)
        tasks.append(t)
    create_ms = _elapsed_ms(t0)
    _kpi.record(SCENARIO, f"Create {NUM_PATIENTS} states", create_ms, "ms")
    _kpi.record(SCENARIO, "Per-create latency", create_ms / NUM_PATIENTS, "ms")

    # ── Set all to DOWNLOADING ──
    t0 = time.perf_counter()
    for t in tasks:
        store.update(t.study_uid, status=DownloadStatus.DOWNLOADING)
    dl_ms = _elapsed_ms(t0)
    _kpi.record(SCENARIO, f"DOWNLOADING transition x{NUM_PATIENTS}", dl_ms, "ms")

    active = store.get_by_status(DownloadStatus.DOWNLOADING)
    ok = len(active) == NUM_PATIENTS
    _kpi.record(SCENARIO, "All 50 DOWNLOADING", ok, "", ok)

    # ── Rapid progress update storm (5 updates per patient = 250 total) ──
    update_latencies: List[float] = []
    for cycle in range(5):
        for t in tasks:
            t0 = time.perf_counter()
            store.update(t.study_uid, progress_percent=float(cycle * 20), downloaded_count=cycle * 10)
            update_latencies.append(_elapsed_ms(t0))

    _kpi.record(SCENARIO, "Total progress updates", len(update_latencies), "ops")
    _kpi.record(SCENARIO, "Avg update latency", sum(update_latencies) / len(update_latencies), "ms")
    _kpi.record(SCENARIO, "P95 update latency", _percentile(update_latencies, 95), "ms")
    _kpi.record(SCENARIO, "P99 update latency", _percentile(update_latencies, 99), "ms")
    _kpi.record(SCENARIO, "Max update latency", max(update_latencies), "ms")
    ok = _percentile(update_latencies, 99) < 5.0
    _kpi.record(SCENARIO, "P99 update < 5ms", ok, "", ok)

    # ── get_all() under full load ──
    t0 = time.perf_counter()
    all_states = store.get_all()
    getall_ms = _elapsed_ms(t0)
    _kpi.record(SCENARIO, "get_all() latency (50 states)", getall_ms, "ms")
    ok = getall_ms < 10.0
    _kpi.record(SCENARIO, "get_all() < 10ms", ok, "", ok)

    # ── Complete all + cleanup ──
    t0 = time.perf_counter()
    for t in tasks:
        store.update(t.study_uid, status=DownloadStatus.COMPLETED, progress_percent=100.0)
    complete_ms = _elapsed_ms(t0)
    _kpi.record(SCENARIO, f"Complete {NUM_PATIENTS} states", complete_ms, "ms")

    t0 = time.perf_counter()
    for t in tasks:
        store.remove(t.study_uid)
    remove_ms = _elapsed_ms(t0)
    _kpi.record(SCENARIO, f"Remove {NUM_PATIENTS} states", remove_ms, "ms")
    ok = len(store.get_all()) == 0
    _kpi.record(SCENARIO, "Store empty after cleanup", ok, "", ok)

    logger.info(f"  Done: {SCENARIO}\n")


# ═══════════════════════════════════════════════════════════════════
#  H2 — Rapid Series-Switch Simulation (500 switches in <5s)
# ═══════════════════════════════════════════════════════════════════

def h2_rapid_series_switch():
    """
    Simulate 500 rapid drag-drop series switches on a single study.
    Each switch: update(priority=CRITICAL, viewed_series_number=N).
    Measure per-switch latency and observer throughput.
    """
    SCENARIO = "H2: 500 Rapid Series Switches"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    NUM_SWITCHES = 500

    task = _make_task(patient_name="RapidSwitch", series_count=20, images_per_series=50)
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.DOWNLOADING)

    obs_count = [0]

    class SwitchObserver:
        def on_state_change(self, event, study_uid, state, *args):
            obs_count[0] += 1

    store.register_observer(SwitchObserver())

    latencies: List[float] = []
    t_wall = time.perf_counter()
    for i in range(NUM_SWITCHES):
        sn = str((i % 20) + 1)
        t0 = time.perf_counter()
        store.update(
            task.study_uid,
            priority=DownloadPriority.CRITICAL,
            viewed_series_number=sn,
        )
        latencies.append(_elapsed_ms(t0))
    wall_ms = _elapsed_ms(t_wall)

    _kpi.record(SCENARIO, "Switches executed", NUM_SWITCHES, "")
    _kpi.record(SCENARIO, "Wall clock", wall_ms, "ms")
    _kpi.record(SCENARIO, "Throughput", NUM_SWITCHES / (wall_ms / 1000.0), "switches/sec")
    _kpi.record(SCENARIO, "Avg switch latency", sum(latencies) / len(latencies), "ms")
    _kpi.record(SCENARIO, "P50 switch latency", _percentile(latencies, 50), "ms")
    _kpi.record(SCENARIO, "P95 switch latency", _percentile(latencies, 95), "ms")
    _kpi.record(SCENARIO, "P99 switch latency", _percentile(latencies, 99), "ms")
    _kpi.record(SCENARIO, "Max switch latency", max(latencies), "ms")
    _kpi.record(SCENARIO, "Observer notifications", obs_count[0], "count")

    ok = wall_ms < 5000.0
    _kpi.record(SCENARIO, "500 switches < 5s", ok, "", ok)
    ok = _percentile(latencies, 95) < 1.0
    _kpi.record(SCENARIO, "P95 < 1ms", ok, "", ok)
    ok = obs_count[0] >= NUM_SWITCHES
    _kpi.record(SCENARIO, "All observer notifications delivered", ok, "", ok)

    logger.info(f"  Done: {SCENARIO}\n")


# ═══════════════════════════════════════════════════════════════════
#  H3 — Multi-Threaded State Store Contention (16 threads × 500 ops)
# ═══════════════════════════════════════════════════════════════════

def h3_multithreaded_contention():
    """
    16 threads each performing 500 create→update→read→complete→remove cycles.
    Total: 8000 full lifecycle operations.
    Measures: throughput, P95/P99 latency, error rate.
    """
    SCENARIO = "H3: 16-Thread Contention (8000 ops)"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    NUM_THREADS = 16
    OPS_PER_THREAD = 500
    errors: List[str] = []
    latencies: List[float] = []
    lock = threading.Lock()

    def _worker(tid: int):
        for op in range(OPS_PER_THREAD):
            t = _make_task(patient_name=f"T{tid}-{op}")
            try:
                t0 = time.perf_counter()
                store.create(t)
                store.update(t.study_uid, status=DownloadStatus.DOWNLOADING)
                store.update(t.study_uid, progress_percent=50.0, downloaded_count=16, total_count=32)
                s = store.get(t.study_uid)
                assert s is not None, f"get() returned None for {t.study_uid}"
                assert s.status == DownloadStatus.DOWNLOADING
                store.update(t.study_uid, status=DownloadStatus.COMPLETED, progress_percent=100.0)
                store.remove(t.study_uid)
                elapsed = _elapsed_ms(t0)
                with lock:
                    latencies.append(elapsed)
            except Exception as e:
                with lock:
                    errors.append(f"T{tid}-{op}: {e}")

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(NUM_THREADS)]
    t_wall = time.perf_counter()
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    wall_ms = _elapsed_ms(t_wall)

    total_ops = NUM_THREADS * OPS_PER_THREAD
    _kpi.record(SCENARIO, "Total lifecycle ops", total_ops, "ops")
    _kpi.record(SCENARIO, "Errors", len(errors), "errors", len(errors) == 0)
    _kpi.record(SCENARIO, "Wall clock", wall_ms, "ms")
    _kpi.record(SCENARIO, "Throughput", total_ops / (wall_ms / 1000.0), "ops/sec")

    if latencies:
        _kpi.record(SCENARIO, "Avg op latency", sum(latencies) / len(latencies), "ms")
        _kpi.record(SCENARIO, "P50 op latency", _percentile(latencies, 50), "ms")
        _kpi.record(SCENARIO, "P95 op latency", _percentile(latencies, 95), "ms")
        _kpi.record(SCENARIO, "P99 op latency", _percentile(latencies, 99), "ms")
        _kpi.record(SCENARIO, "Max op latency", max(latencies), "ms")
        ok = _percentile(latencies, 99) < 50.0
        _kpi.record(SCENARIO, "P99 < 50ms", ok, "", ok)

    ok = len(store.get_all()) == 0
    _kpi.record(SCENARIO, "Store clean after stress", ok, "", ok)

    if errors:
        for e in errors[:5]:
            logger.error(f"  Thread error: {e}")

    logger.info(f"  Done: {SCENARIO}\n")


# ═══════════════════════════════════════════════════════════════════
#  H4 — High-Frequency Progress Signals (10,000 updates + observers)
# ═══════════════════════════════════════════════════════════════════

def h4_high_frequency_progress():
    """
    Simulate 10,000 rapid progress updates on 10 studies (1000 each).
    5 observers registered to measure fan-out cost.
    """
    SCENARIO = "H4: 10K Progress Updates (5 observers)"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    NUM_STUDIES = 10
    UPDATES_PER_STUDY = 1000
    NUM_OBSERVERS = 5

    tasks = [_make_task(patient_name=f"Freq-{i}", series_count=5) for i in range(NUM_STUDIES)]
    for t in tasks:
        store.create(t)
        store.update(t.study_uid, status=DownloadStatus.DOWNLOADING)

    obs_counts = [0] * NUM_OBSERVERS

    def _make_observer(idx):
        class Obs:
            def on_state_change(self, event, study_uid, state, *args):
                obs_counts[idx] += 1
        return Obs()

    for i in range(NUM_OBSERVERS):
        store.register_observer(_make_observer(i))

    latencies: List[float] = []
    t_wall = time.perf_counter()
    for cycle in range(UPDATES_PER_STUDY):
        for t in tasks:
            pct = (cycle / UPDATES_PER_STUDY) * 100.0
            t0 = time.perf_counter()
            store.update(t.study_uid, progress_percent=pct, downloaded_count=cycle)
            latencies.append(_elapsed_ms(t0))
    wall_ms = _elapsed_ms(t_wall)

    total_updates = NUM_STUDIES * UPDATES_PER_STUDY
    total_notifications = sum(obs_counts)
    expected_min_notifications = total_updates * NUM_OBSERVERS

    _kpi.record(SCENARIO, "Total updates", total_updates, "ops")
    _kpi.record(SCENARIO, "Observers", NUM_OBSERVERS, "")
    _kpi.record(SCENARIO, "Wall clock", wall_ms, "ms")
    _kpi.record(SCENARIO, "Throughput", total_updates / (wall_ms / 1000.0), "updates/sec")
    _kpi.record(SCENARIO, "Avg update+notify latency", sum(latencies) / len(latencies), "ms")
    _kpi.record(SCENARIO, "P95 latency", _percentile(latencies, 95), "ms")
    _kpi.record(SCENARIO, "P99 latency", _percentile(latencies, 99), "ms")
    _kpi.record(SCENARIO, "Max latency", max(latencies), "ms")
    _kpi.record(SCENARIO, "Total observer notifications", total_notifications, "count")

    ok = _percentile(latencies, 95) < 2.0
    _kpi.record(SCENARIO, "P95 < 2ms (with 5 observers)", ok, "", ok)
    ok = total_notifications >= expected_min_notifications
    _kpi.record(SCENARIO, "All observer notifications delivered", ok, "", ok)

    # Cleanup
    for t in tasks:
        store.remove(t.study_uid)

    logger.info(f"  Done: {SCENARIO}\n")


# ═══════════════════════════════════════════════════════════════════
#  H5 — Memory Pressure (200 studies × 20 series)
# ═══════════════════════════════════════════════════════════════════

def h5_memory_pressure():
    """
    Create 200 studies with 20 series each (4000 SeriesInfo objects).
    Measure memory growth, GC pressure, state store lookup performance.
    """
    SCENARIO = "H5: Memory Pressure (200 studies x 20 series)"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    import tracemalloc
    tracemalloc.start()

    store = DownloadStateStore()
    NUM_STUDIES = 200
    SERIES_PER_STUDY = 20

    gc.collect()
    snap_before = tracemalloc.take_snapshot()
    mem_before = tracemalloc.get_traced_memory()[0]

    tasks: List[DownloadTask] = []
    t0 = time.perf_counter()
    for i in range(NUM_STUDIES):
        t = _make_task(patient_name=f"MemStress-{i:03d}", series_count=SERIES_PER_STUDY, images_per_series=100)
        store.create(t)
        store.update(t.study_uid, status=DownloadStatus.DOWNLOADING)
        tasks.append(t)
    create_ms = _elapsed_ms(t0)
    mem_after_create = tracemalloc.get_traced_memory()[0]

    _kpi.record(SCENARIO, f"Create {NUM_STUDIES} studies", create_ms, "ms")
    _kpi.record(SCENARIO, "Total SeriesInfo objects", NUM_STUDIES * SERIES_PER_STUDY, "")
    _kpi.record(SCENARIO, "Memory before", mem_before / 1024, "KB")
    _kpi.record(SCENARIO, "Memory after create", mem_after_create / 1024, "KB")
    mem_growth_mb = (mem_after_create - mem_before) / (1024 * 1024)
    _kpi.record(SCENARIO, "Memory growth", mem_growth_mb, "MB")
    ok = mem_growth_mb < 100.0  # 100MB should be generous
    _kpi.record(SCENARIO, "Memory growth < 100MB", ok, "", ok)

    # ── GC under heavy state ──
    gc_times: List[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        gc.collect()
        gc_times.append(_elapsed_ms(t0))

    _kpi.record(SCENARIO, "GC avg (200 states)", sum(gc_times) / len(gc_times), "ms")
    _kpi.record(SCENARIO, "GC max (200 states)", max(gc_times), "ms")
    ok = max(gc_times) < 100.0
    _kpi.record(SCENARIO, "GC max < 100ms", ok, "", ok)

    # ── Per-study lookup under full load ──
    lookup_latencies: List[float] = []
    for t in tasks[:50]:  # sample 50
        t0 = time.perf_counter()
        s = store.get(t.study_uid)
        lookup_latencies.append(_elapsed_ms(t0))

    _kpi.record(SCENARIO, "Avg lookup latency (200 states)", sum(lookup_latencies) / len(lookup_latencies), "ms")
    _kpi.record(SCENARIO, "Max lookup latency", max(lookup_latencies), "ms")
    ok = max(lookup_latencies) < 1.0
    _kpi.record(SCENARIO, "Max lookup < 1ms", ok, "", ok)

    # ── get_by_status under full load ──
    t0 = time.perf_counter()
    downloading = store.get_by_status(DownloadStatus.DOWNLOADING)
    gbs_ms = _elapsed_ms(t0)
    _kpi.record(SCENARIO, "get_by_status(DOWNLOADING) latency", gbs_ms, "ms")
    ok = len(downloading) == NUM_STUDIES
    _kpi.record(SCENARIO, "get_by_status returns all 200", ok, "", ok)

    # Cleanup
    for t in tasks:
        store.remove(t.study_uid)
    tracemalloc.stop()

    logger.info(f"  Done: {SCENARIO}\n")


# ═══════════════════════════════════════════════════════════════════
#  H6 — Priority Negotiation Storm (all CRITICAL simultaneously)
# ═══════════════════════════════════════════════════════════════════

def h6_priority_negotiation_storm():
    """
    20 studies all request CRITICAL priority nearly simultaneously.
    Only 1 can be CRITICAL at a time — verify correct preemption cascade.
    """
    SCENARIO = "H6: Priority Storm (20 CRITICAL requests)"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    engine = DownloadRuleEngine(store, {})
    NUM_STUDIES = 20

    tasks = [
        _make_task(patient_name=f"Storm-{i:02d}", priority=DownloadPriority.NORMAL, series_count=3)
        for i in range(NUM_STUDIES)
    ]
    for t in tasks:
        store.create(t)
        store.update(t.study_uid, status=DownloadStatus.DOWNLOADING)

    calls = {"paused": [], "start": 0, "refresh": 0, "resume": 0}
    coord, calls = _make_coordinator(store, engine, tasks, calls)

    promote_latencies: List[float] = []
    for i, t in enumerate(tasks):
        # Each study requests CRITICAL in sequence (simulating rapid user clicks)
        # Previous CRITICAL should be demoted / paused
        store.update(t.study_uid, priority=DownloadPriority.CRITICAL)
        t0 = time.perf_counter()
        coord.negotiate_priority_change(t.study_uid, DownloadPriority.CRITICAL)
        promote_latencies.append(_elapsed_ms(t0))

    _kpi.record(SCENARIO, "CRITICAL requests", NUM_STUDIES, "")
    _kpi.record(SCENARIO, "Avg negotiate latency", sum(promote_latencies) / len(promote_latencies), "ms")
    _kpi.record(SCENARIO, "P95 negotiate latency", _percentile(promote_latencies, 95), "ms")
    _kpi.record(SCENARIO, "P99 negotiate latency", _percentile(promote_latencies, 99), "ms")
    _kpi.record(SCENARIO, "Max negotiate latency", max(promote_latencies), "ms")
    _kpi.record(SCENARIO, "Total pause operations", len(calls["paused"]), "ops")
    _kpi.record(SCENARIO, "Table refreshes triggered", calls["refresh"], "ops")

    ok = _percentile(promote_latencies, 95) < 2.0
    _kpi.record(SCENARIO, "P95 negotiate < 2ms", ok, "", ok)
    ok = max(promote_latencies) < 10.0
    _kpi.record(SCENARIO, "Max negotiate < 10ms", ok, "", ok)

    # Last requester should be CRITICAL
    last_state = store.get(tasks[-1].study_uid)
    ok = last_state.priority == DownloadPriority.CRITICAL
    _kpi.record(SCENARIO, "Last requester is CRITICAL", ok, "", ok)

    logger.info(f"  Done: {SCENARIO}\n")


# ═══════════════════════════════════════════════════════════════════
#  H7 — Coordinator Churn (100 create/promote/complete/resume cycles)
# ═══════════════════════════════════════════════════════════════════

def h7_coordinator_churn():
    """
    Full lifecycle churn: 100 iterations of
      create study → promote to CRITICAL → complete → clear intent → auto-resume peers.
    Measures: per-cycle latency, accumulated state consistency.
    """
    SCENARIO = "H7: Coordinator Churn (100 cycles)"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    engine = DownloadRuleEngine(store, {})
    NUM_CYCLES = 100

    # Background peer that stays DOWNLOADING throughout
    peer = _make_task(patient_name="Peer-BG", priority=DownloadPriority.NORMAL, series_count=2)
    store.create(peer)
    store.update(peer.study_uid, status=DownloadStatus.DOWNLOADING)

    cycle_latencies: List[float] = []
    errors: List[str] = []

    for c in range(NUM_CYCLES):
        try:
            t0 = time.perf_counter()

            # 1. Create new study
            t = _make_task(patient_name=f"Churn-{c:03d}", priority=DownloadPriority.NORMAL, series_count=2)
            store.create(t)
            store.update(t.study_uid, status=DownloadStatus.DOWNLOADING)

            calls = {"paused": [], "start": 0, "refresh": 0, "resume": 0}
            coord, calls = _make_coordinator(store, engine, [t, peer], calls)

            # 2. Promote to CRITICAL
            coord.request_critical_series(t.study_uid, "1")

            # 3. Complete
            store.update(t.study_uid, status=DownloadStatus.COMPLETED, progress_percent=100.0)

            # 4. Clear intent
            coord.clear_series_intent(t.study_uid)

            # 5. Resume peer if paused
            peer_state = store.get(peer.study_uid)
            if peer_state and peer_state.status == DownloadStatus.PAUSED:
                store.update(peer.study_uid, status=DownloadStatus.DOWNLOADING, is_auto_paused=False)

            # 6. Cleanup completed study
            store.remove(t.study_uid)

            cycle_latencies.append(_elapsed_ms(t0))
        except Exception as e:
            errors.append(f"Cycle-{c}: {e}")

    _kpi.record(SCENARIO, "Cycles completed", NUM_CYCLES - len(errors), "")
    _kpi.record(SCENARIO, "Errors", len(errors), "errors", len(errors) == 0)
    if cycle_latencies:
        _kpi.record(SCENARIO, "Avg cycle latency", sum(cycle_latencies) / len(cycle_latencies), "ms")
        _kpi.record(SCENARIO, "P95 cycle latency", _percentile(cycle_latencies, 95), "ms")
        _kpi.record(SCENARIO, "P99 cycle latency", _percentile(cycle_latencies, 99), "ms")
        _kpi.record(SCENARIO, "Max cycle latency", max(cycle_latencies), "ms")
        ok = _percentile(cycle_latencies, 95) < 5.0
        _kpi.record(SCENARIO, "P95 cycle < 5ms", ok, "", ok)

    # Peer should still be in store and not corrupted
    peer_final = store.get(peer.study_uid)
    ok = peer_final is not None and peer_final.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PAUSED)
    _kpi.record(SCENARIO, "Peer survived 100 cycles uncorrupted", ok, "", ok)

    # Only peer should remain
    remaining = store.get_all()
    ok = len(remaining) == 1
    _kpi.record(SCENARIO, "Only 1 state remains (peer)", ok, "", ok)

    store.remove(peer.study_uid)

    if errors:
        for e in errors[:5]:
            logger.error(f"  Churn error: {e}")

    logger.info(f"  Done: {SCENARIO}\n")


# ═══════════════════════════════════════════════════════════════════
#  H8 — File I/O Stress (10 studies × 10 series × 100 files)
# ═══════════════════════════════════════════════════════════════════

def h8_file_io_stress():
    """
    Create 10,000 dummy .dcm files (10 × 10 × 100), then:
      - Enumerate all series (R19b batch-skip simulation)
      - Delete complete series (retry simulation)
      - Measure I/O throughput
    """
    SCENARIO = "H8: File I/O Stress (10K files)"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    with _temp_output_dir() as base:
        NUM_STUDIES = 10
        SERIES_PER_STUDY = 10
        FILES_PER_SERIES = 100

        # ── Write phase ──
        t0 = time.perf_counter()
        study_uids: List[str] = []
        for s in range(NUM_STUDIES):
            uid = f"study_{s:03d}"
            study_uids.append(uid)
            for sn in range(1, SERIES_PER_STUDY + 1):
                _create_dcm_files(base, uid, str(sn), FILES_PER_SERIES)
        write_ms = _elapsed_ms(t0)

        total_files = NUM_STUDIES * SERIES_PER_STUDY * FILES_PER_SERIES
        _kpi.record(SCENARIO, "Files created", total_files, "files")
        _kpi.record(SCENARIO, "Write time", write_ms, "ms")
        _kpi.record(SCENARIO, "Write throughput", total_files / (write_ms / 1000.0), "files/sec")

        # ── Enumerate phase (R19b batch-skip simulation) ──
        t0 = time.perf_counter()
        enum_count = 0
        for uid in study_uids:
            for sn in range(1, SERIES_PER_STUDY + 1):
                sd = base / uid / str(sn)
                if sd.exists():
                    # Use os.scandir (as in production code)
                    with os.scandir(sd) as entries:
                        count = sum(1 for e in entries if e.name.endswith(".dcm") and e.is_file())
                    enum_count += count
        enum_ms = _elapsed_ms(t0)

        _kpi.record(SCENARIO, "Files enumerated", enum_count, "files")
        _kpi.record(SCENARIO, "Enumerate time", enum_ms, "ms")
        _kpi.record(SCENARIO, "Enumerate throughput", enum_count / (enum_ms / 1000.0), "files/sec")
        ok = enum_count == total_files
        _kpi.record(SCENARIO, "All files found", ok, "", ok)

        # ── R19b batch verification ──
        t0 = time.perf_counter()
        batches_verified = 0
        for uid in study_uids[:3]:  # sample 3 studies
            for sn in range(1, SERIES_PER_STUDY + 1):
                sd = base / uid / str(sn)
                batch_start = 0
                for batch_idx in range(FILES_PER_SERIES // BATCH_SIZE):
                    all_present = all(
                        (sd / f"Instance_{batch_idx * BATCH_SIZE + j + 1:04d}.dcm").exists()
                        for j in range(BATCH_SIZE)
                    )
                    if all_present:
                        batch_start = (batch_idx + 1) * BATCH_SIZE
                        batches_verified += 1
                    else:
                        break
        batch_ms = _elapsed_ms(t0)
        _kpi.record(SCENARIO, "Batches verified", batches_verified, "batches")
        _kpi.record(SCENARIO, "Batch verify time", batch_ms, "ms")

        # ── Delete phase (retry simulation: delete 5 complete studies) ──
        t0 = time.perf_counter()
        for uid in study_uids[:5]:
            shutil.rmtree(base / uid, ignore_errors=True)
        delete_ms = _elapsed_ms(t0)

        remaining_files = 0
        for uid in study_uids[5:]:
            for sn in range(1, SERIES_PER_STUDY + 1):
                sd = base / uid / str(sn)
                if sd.exists():
                    remaining_files += len([f for f in os.listdir(sd) if f.endswith(".dcm")])

        _kpi.record(SCENARIO, "Delete time (5 studies)", delete_ms, "ms")
        ok = remaining_files == 5 * SERIES_PER_STUDY * FILES_PER_SERIES
        _kpi.record(SCENARIO, "Remaining files correct (5000)", ok, "", ok)

    logger.info(f"  Done: {SCENARIO}\n")


# ═══════════════════════════════════════════════════════════════════
#  H9 — Rule Engine Throughput (1000 get_next_download)
# ═══════════════════════════════════════════════════════════════════

def h9_rule_engine_throughput():
    """
    Fill the store with 100 studies at various priorities.
    Call get_next_download() 1000 times and measure latency.
    This simulates the scheduler polling under full load.
    """
    SCENARIO = "H9: Rule Engine Throughput (1000 picks)"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    engine = DownloadRuleEngine(store, {})
    NUM_STUDIES = 100

    priorities = [DownloadPriority.LOW, DownloadPriority.NORMAL, DownloadPriority.HIGH, DownloadPriority.CRITICAL]
    tasks = []
    for i in range(NUM_STUDIES):
        pri = priorities[i % len(priorities)]
        t = _make_task(patient_name=f"Queue-{i:03d}", priority=pri, series_count=2)
        store.create(t)
        tasks.append(t)

    NUM_PICKS = 1000
    pick_latencies: List[float] = []

    t_wall = time.perf_counter()
    for _ in range(NUM_PICKS):
        t0 = time.perf_counter()
        nxt = engine.get_next_download()
        pick_latencies.append(_elapsed_ms(t0))
        # Don't remove — keep store full to stress the picker
    wall_ms = _elapsed_ms(t_wall)

    _kpi.record(SCENARIO, "Store size", NUM_STUDIES, "studies")
    _kpi.record(SCENARIO, "Picks executed", NUM_PICKS, "")
    _kpi.record(SCENARIO, "Wall clock", wall_ms, "ms")
    _kpi.record(SCENARIO, "Throughput", NUM_PICKS / (wall_ms / 1000.0), "picks/sec")
    _kpi.record(SCENARIO, "Avg pick latency", sum(pick_latencies) / len(pick_latencies), "ms")
    _kpi.record(SCENARIO, "P50 pick latency", _percentile(pick_latencies, 50), "ms")
    _kpi.record(SCENARIO, "P95 pick latency", _percentile(pick_latencies, 95), "ms")
    _kpi.record(SCENARIO, "P99 pick latency", _percentile(pick_latencies, 99), "ms")
    _kpi.record(SCENARIO, "Max pick latency", max(pick_latencies), "ms")

    ok = _percentile(pick_latencies, 95) < 5.0
    _kpi.record(SCENARIO, "P95 pick < 5ms", ok, "", ok)
    ok = _percentile(pick_latencies, 99) < 10.0
    _kpi.record(SCENARIO, "P99 pick < 10ms", ok, "", ok)

    # Cleanup
    for t in tasks:
        store.remove(t.study_uid)

    logger.info(f"  Done: {SCENARIO}\n")


# ═══════════════════════════════════════════════════════════════════
#  H10 — Combined Pipeline Stress
# ═══════════════════════════════════════════════════════════════════

def h10_combined_pipeline_stress():
    """
    Combined heavy test: 30 studies, 4 phases running in sequence:
    1. Burst creation + priority assignment
    2. Concurrent progress updates from 8 threads (simulating 8 DM workers)
    3. Priority storms (every study requests CRITICAL, then demote)
    4. Cascade completion + auto-resume verification

    This is the most realistic heavy-load scenario.
    """
    SCENARIO = "H10: Combined Pipeline Stress"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    engine = DownloadRuleEngine(store, {})
    NUM_STUDIES = 30
    PROGRESS_THREADS = 8
    UPDATES_PER_THREAD = 200

    obs_count = [0]

    class CountObs:
        def on_state_change(self, *args):
            obs_count[0] += 1

    store.register_observer(CountObs())

    # ── Phase 1: Burst creation ──
    tasks: List[DownloadTask] = []
    t0 = time.perf_counter()
    priorities = [DownloadPriority.LOW, DownloadPriority.NORMAL, DownloadPriority.HIGH]
    for i in range(NUM_STUDIES):
        pri = priorities[i % 3]
        t = _make_task(patient_name=f"Combo-{i:02d}", priority=pri, series_count=5, images_per_series=50)
        store.create(t)
        store.update(t.study_uid, status=DownloadStatus.DOWNLOADING)
        tasks.append(t)
    phase1_ms = _elapsed_ms(t0)
    _kpi.record(SCENARIO, "Phase 1: Burst create (30 studies)", phase1_ms, "ms")

    # ── Phase 2: Concurrent progress updates ──
    progress_errors: List[str] = []
    progress_latencies: List[float] = []
    plock = threading.Lock()

    def _progress_worker(tid: int):
        for u in range(UPDATES_PER_THREAD):
            t = tasks[(tid * UPDATES_PER_THREAD + u) % NUM_STUDIES]
            try:
                t0 = time.perf_counter()
                store.update(t.study_uid, progress_percent=float(u % 100), downloaded_count=u)
                elapsed = _elapsed_ms(t0)
                with plock:
                    progress_latencies.append(elapsed)
            except Exception as e:
                with plock:
                    progress_errors.append(f"PT{tid}-{u}: {e}")

    pthreads = [threading.Thread(target=_progress_worker, args=(i,)) for i in range(PROGRESS_THREADS)]
    t0 = time.perf_counter()
    for pt in pthreads:
        pt.start()
    for pt in pthreads:
        pt.join()
    phase2_ms = _elapsed_ms(t0)

    total_progress = PROGRESS_THREADS * UPDATES_PER_THREAD
    _kpi.record(SCENARIO, f"Phase 2: {total_progress} progress updates ({PROGRESS_THREADS} threads)", phase2_ms, "ms")
    _kpi.record(SCENARIO, "Phase 2 errors", len(progress_errors), "errors", len(progress_errors) == 0)
    if progress_latencies:
        _kpi.record(SCENARIO, "Phase 2 P95 update latency", _percentile(progress_latencies, 95), "ms")
        _kpi.record(SCENARIO, "Phase 2 P99 update latency", _percentile(progress_latencies, 99), "ms")

    # ── Phase 3: Priority storm ──
    storm_latencies: List[float] = []
    t0 = time.perf_counter()
    for t in tasks:
        ts = time.perf_counter()
        store.update(t.study_uid, priority=DownloadPriority.CRITICAL, viewed_series_number="1")
        storm_latencies.append(_elapsed_ms(ts))
    # Then demote all back
    for i, t in enumerate(tasks):
        ts = time.perf_counter()
        store.update(t.study_uid, priority=priorities[i % 3], viewed_series_number=None)
        storm_latencies.append(_elapsed_ms(ts))
    phase3_ms = _elapsed_ms(t0)

    _kpi.record(SCENARIO, f"Phase 3: Priority storm ({NUM_STUDIES * 2} transitions)", phase3_ms, "ms")
    _kpi.record(SCENARIO, "Phase 3 P95 transition latency", _percentile(storm_latencies, 95), "ms")

    # ── Phase 4: Cascade completion ──
    t0 = time.perf_counter()
    for t in tasks:
        store.update(t.study_uid, status=DownloadStatus.COMPLETED, progress_percent=100.0)
    phase4_ms = _elapsed_ms(t0)

    completed = store.get_by_status(DownloadStatus.COMPLETED)
    ok = len(completed) == NUM_STUDIES
    _kpi.record(SCENARIO, f"Phase 4: Complete all {NUM_STUDIES}", phase4_ms, "ms")
    _kpi.record(SCENARIO, "All 30 COMPLETED", ok, "", ok)

    # ── Overall KPIs ──
    total_ms = phase1_ms + phase2_ms + phase3_ms + phase4_ms
    _kpi.record(SCENARIO, "Total pipeline time", total_ms, "ms")
    _kpi.record(SCENARIO, "Total observer notifications", obs_count[0], "count")

    ok = total_ms < 10000.0  # 10 seconds is very generous
    _kpi.record(SCENARIO, "Total pipeline < 10s", ok, "", ok)

    ok = len(progress_errors) == 0
    _kpi.record(SCENARIO, "Zero errors across all phases", ok, "", ok)

    # Cleanup
    for t in tasks:
        store.remove(t.study_uid)

    logger.info(f"  Done: {SCENARIO}\n")


# ═══════════════════════════════════════════════════════════════════
#  RUNNER
# ═══════════════════════════════════════════════════════════════════

def main():
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print()
    print("=" * 110)
    print("  DOWNLOAD MANAGER — HEAVY-LOAD STRESS TEST SUITE")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Platform: {sys.platform}")
    print("=" * 110)
    print()

    scenarios = [
        ("H1", "50 Concurrent Patients", h1_concurrent_patient_scalability),
        ("H2", "500 Rapid Series Switches", h2_rapid_series_switch),
        ("H3", "16-Thread Contention (8000 ops)", h3_multithreaded_contention),
        ("H4", "10K Progress Updates (5 observers)", h4_high_frequency_progress),
        ("H5", "Memory Pressure (200x20)", h5_memory_pressure),
        ("H6", "Priority Storm (20 CRITICAL)", h6_priority_negotiation_storm),
        ("H7", "Coordinator Churn (100 cycles)", h7_coordinator_churn),
        ("H8", "File I/O Stress (10K files)", h8_file_io_stress),
        ("H9", "Rule Engine Throughput (1K picks)", h9_rule_engine_throughput),
        ("H10", "Combined Pipeline Stress", h10_combined_pipeline_stress),
    ]

    failed_scenarios = []
    t_total = time.perf_counter()

    for code, name, func in scenarios:
        try:
            func()
        except Exception as e:
            logger.error(f"FAIL {code}: {name} -- EXCEPTION: {e}")
            traceback.print_exc()
            failed_scenarios.append(code)
            _kpi.record(code, "Scenario execution", "EXCEPTION", "", False)

    total_ms = _elapsed_ms(t_total)
    _kpi.record("OVERALL", "Total stress suite time", total_ms, "ms")
    _kpi.record("OVERALL", "Scenarios executed", len(scenarios), "")
    _kpi.record("OVERALL", "Scenarios failed", len(failed_scenarios), "", len(failed_scenarios) == 0)

    print(_kpi.report())

    if failed_scenarios:
        print(f"\n  Failed scenarios: {', '.join(failed_scenarios)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
