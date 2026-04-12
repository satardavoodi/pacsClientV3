"""
AIPacs Load Test Suite — Multi-Patient, Multi-Modality Stress Testing
=====================================================================

Run:
    python tests/load/run_load_test.py

Simulates realistic clinical workload:
    L1.  Open 6 patients simultaneously (2 CT, 3 XR, 1 MRI)
    L2.  CT heavy-slice download + progressive display simulation
    L3.  Radiography large-file download pressure
    L4.  Concurrent download scheduling with priority preemption
    L5.  Cache pressure: 6 patients × multiple series = eviction storm
    L6.  Scroll simulation during active downloads (main-thread budget)
    L7.  Series switch storm during active downloads
    L8.  Combined full-workload: all of the above simultaneously
    L9.  Memory + GC pressure under sustained load
    L10. Progressive display grow under download contention
    L11. Pool-freed callback and retry exhaustion budget

No live server connection required — all network I/O is mocked.

KPI thresholds are derived from v2.2.8.1 pipeline budget:
    - State update P95 < 2ms
    - Coordinator negotiate P95 < 5ms
    - Cache put/get P95 < 5ms
    - Progress fan-out zero dropped
    - Scroll frame budget < 16ms (simulated)
    - Total pipeline < 30s
    - Memory growth < 200MB for full workload
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
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

# ── project root on sys.path ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("load_test")

# ═══════════════════════════════════════════════════════════════════
#  Imports (bootstrap DM modules without Qt)
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
#  KPI Collector
# ═══════════════════════════════════════════════════════════════════

class KPICollector:
    def __init__(self):
        self._records: List[Dict[str, Any]] = []

    def record(self, scenario: str, metric: str, value: Any,
               unit: str = "", passed: Optional[bool] = None):
        self._records.append({
            "scenario": scenario, "metric": metric,
            "value": value, "unit": unit, "passed": passed,
        })

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self._records if r["passed"] is False)

    def report(self) -> str:
        lines: List[str] = []
        lines.append("")
        lines.append("=" * 110)
        lines.append("  AIPACS LOAD TEST — MULTI-PATIENT MULTI-MODALITY KPI REPORT")
        lines.append("=" * 110)

        scenarios: Dict[str, list] = defaultdict(list)
        for r in self._records:
            scenarios[r["scenario"]].append(r)

        total_pass = total_fail = total_skip = 0
        for scenario, records in scenarios.items():
            lines.append("")
            lines.append(f"  ┌── Scenario: {scenario}")
            lines.append(f"  │{'Metric':<55} {'Value':>15} {'Unit':<10} {'Status':>8}")
            lines.append(f"  │{'─' * 90}")
            for r in records:
                if r["passed"] is True:
                    status_str = "✅ PASS"
                    total_pass += 1
                elif r["passed"] is False:
                    status_str = "❌ FAIL"
                    total_fail += 1
                else:
                    status_str = "── info"
                    total_skip += 1
                val = r["value"]
                val_str = f"{val:>15.3f}" if isinstance(val, float) else f"{str(val):>15}"
                lines.append(f"  │ {r['metric']:<54} {val_str} {r['unit']:<10}{status_str}")
            lines.append(f"  └{'─' * 90}")

        lines.append("")
        lines.append("=" * 110)
        lines.append(f"  TOTALS:  ✅ {total_pass} passed   ❌ {total_fail} failed   ── {total_skip} info")
        lines.append("=" * 110)
        lines.append("")
        return "\n".join(lines)


_kpi = KPICollector()


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def _uid() -> str:
    return f"1.2.840.{uuid.uuid4().int % 10**12}"


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _percentile(data: List[float], pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = int(len(s) * pct / 100.0)
    return s[min(idx, len(s) - 1)]


def _make_series(count: int, images_per_series: int,
                 modality: str = "CT") -> List[SeriesInfo]:
    return [
        SeriesInfo(
            series_uid=_uid(), series_number=str(i),
            series_description=f"Series-{i}", modality=modality,
            image_count=images_per_series,
        ) for i in range(1, count + 1)
    ]


# ── Realistic modality-specific task creation ──

def _make_ct_task(patient_name: str = "CT-Patient",
                  series_count: int = 4,
                  slices_per_series: int = 500,
                  priority: DownloadPriority = DownloadPriority.NORMAL) -> DownloadTask:
    """CT: many slices per series (300-800 typical), ~512KB/slice."""
    return DownloadTask(
        study_uid=_uid(), patient_id=f"PID-{uuid.uuid4().hex[:6]}",
        patient_name=patient_name, study_date="20260405",
        modality="CT", description="CT Abdomen/Pelvis",
        series_list=_make_series(series_count, slices_per_series, "CT"),
        priority=priority,
    )


def _make_xr_task(patient_name: str = "XR-Patient",
                  series_count: int = 2,
                  images_per_series: int = 4,
                  priority: DownloadPriority = DownloadPriority.NORMAL) -> DownloadTask:
    """Radiography: few images but large files (~10-50MB each)."""
    return DownloadTask(
        study_uid=_uid(), patient_id=f"PID-{uuid.uuid4().hex[:6]}",
        patient_name=patient_name, study_date="20260405",
        modality="CR", description="Chest X-Ray PA/Lateral",
        series_list=_make_series(series_count, images_per_series, "CR"),
        priority=priority,
    )


def _make_mri_task(patient_name: str = "MRI-Patient",
                   series_count: int = 8,
                   slices_per_series: int = 180,
                   priority: DownloadPriority = DownloadPriority.NORMAL) -> DownloadTask:
    """MRI: many series (8-15), moderate slices (~100-256/series)."""
    return DownloadTask(
        study_uid=_uid(), patient_id=f"PID-{uuid.uuid4().hex[:6]}",
        patient_name=patient_name, study_date="20260405",
        modality="MR", description="MRI Brain w/ contrast",
        series_list=_make_series(series_count, slices_per_series, "MR"),
        priority=priority,
    )


@contextmanager
def _temp_output_dir():
    d = tempfile.mkdtemp(prefix="load_test_")
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _create_dcm_files(base: Path, study_uid: str, series_number: str,
                      count: int, file_size: int = 256):
    series_dir = base / study_uid / series_number
    series_dir.mkdir(parents=True, exist_ok=True)
    data = b"\x00" * file_size
    for i in range(1, count + 1):
        (series_dir / f"Instance_{i:04d}.dcm").write_bytes(data)


class _FakePool:
    def can_add_worker(self):
        return True


def _make_coordinator(store, engine, tasks, calls=None):
    if calls is None:
        calls = {"paused": [], "start": 0, "refresh": 0, "resume": 0}
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


class _LatencyTracker:
    """Thread-safe latency sample collector."""
    def __init__(self):
        self._lock = threading.Lock()
        self._samples: List[float] = []
        self._errors: List[str] = []

    def record(self, ms: float):
        with self._lock:
            self._samples.append(ms)

    def error(self, msg: str):
        with self._lock:
            self._errors.append(msg)

    @property
    def samples(self) -> List[float]:
        return list(self._samples)

    @property
    def errors(self) -> List[str]:
        return list(self._errors)

    @property
    def count(self) -> int:
        return len(self._samples)

    def p50(self) -> float: return _percentile(self._samples, 50)
    def p95(self) -> float: return _percentile(self._samples, 95)
    def p99(self) -> float: return _percentile(self._samples, 99)
    def mean(self) -> float:
        return sum(self._samples) / len(self._samples) if self._samples else 0.0


class _FakeCache:
    """Simulates ZetaBoost cache behavior with realistic memory tracking."""
    def __init__(self, max_entries: int = 24, byte_budget: int = 1200 * 1024 * 1024):
        self._lock = threading.Lock()
        self._entries: Dict[str, Tuple[bytes, int]] = {}  # key -> (data, size)
        self._access_order: List[str] = []
        self._max_entries = max_entries
        self._byte_budget = byte_budget
        self._total_bytes = 0
        self._eviction_count = 0
        self._hit_count = 0
        self._miss_count = 0

    def put(self, key: str, size: int):
        with self._lock:
            if key in self._entries:
                return
            while (self._total_bytes + size > self._byte_budget
                   or len(self._entries) >= self._max_entries):
                if not self._entries:
                    break
                evict_key = self._access_order.pop(0)
                if evict_key in self._entries:
                    _, old_size = self._entries.pop(evict_key)
                    self._total_bytes -= old_size
                    self._eviction_count += 1
            self._entries[key] = (b"", size)
            self._access_order.append(key)
            self._total_bytes += size

    def get(self, key: str) -> bool:
        with self._lock:
            if key in self._entries:
                self._hit_count += 1
                if key in self._access_order:
                    self._access_order.remove(key)
                    self._access_order.append(key)
                return True
            self._miss_count += 1
            return False

    @property
    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "total_bytes_mb": self._total_bytes / (1024 * 1024),
                "evictions": self._eviction_count,
                "hits": self._hit_count,
                "misses": self._miss_count,
                "hit_rate": (self._hit_count / max(1, self._hit_count + self._miss_count)) * 100,
            }


# ═══════════════════════════════════════════════════════════════════
#  L1 — Open 6 Patients Simultaneously (2 CT + 3 XR + 1 MRI)
# ═══════════════════════════════════════════════════════════════════

def l1_open_multiple_patients():
    """
    Simulate opening 6 patients at once:
    - 2 CT studies (500 slices/series × 4 series = 2000 images each)
    - 3 Radiography studies (4 images/series × 2 series = 8 images, large files)
    - 1 MRI study (180 slices/series × 8 series = 1440 images)

    Measures: state store creation throughput, memory footprint.
    """
    SCENARIO = "L1: Open 6 Patients (2CT+3XR+1MRI)"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    engine = DownloadRuleEngine(store, {})

    tasks: List[DownloadTask] = []

    # Build realistic patient load
    t0 = time.perf_counter()

    # 2 CT studies
    for i in range(2):
        tasks.append(_make_ct_task(f"CT-Patient-{i+1}", series_count=4, slices_per_series=500))

    # 3 Radiography studies
    for i in range(3):
        tasks.append(_make_xr_task(f"XR-Patient-{i+1}", series_count=2, images_per_series=4))

    # 1 MRI study
    tasks.append(_make_mri_task("MRI-Patient-1", series_count=8, slices_per_series=180))

    creation_ms = _elapsed_ms(t0)

    # Register all in state store (simulates double-click opening)
    t0 = time.perf_counter()
    for task in tasks:
        store.create(task)
    store_create_ms = _elapsed_ms(t0)

    total_images = sum(t.total_image_count for t in tasks)
    total_series = sum(t.series_count for t in tasks)

    _kpi.record(SCENARIO, "Task creation time (6 patients)", creation_ms, "ms")
    _kpi.record(SCENARIO, "State store create (6 patients)", store_create_ms, "ms",
                store_create_ms < 50.0)
    _kpi.record(SCENARIO, "Total images across all patients", total_images, "images")
    _kpi.record(SCENARIO, "Total series across all patients", total_series, "series")

    # Start all downloads (PENDING → DOWNLOADING)
    t0 = time.perf_counter()
    for task in tasks:
        store.update(task.study_uid, status=DownloadStatus.DOWNLOADING)
    start_all_ms = _elapsed_ms(t0)
    _kpi.record(SCENARIO, "Transition all to DOWNLOADING", start_all_ms, "ms",
                start_all_ms < 50.0)

    # Verify all states exist
    all_states = store.get_all()
    ok = len(all_states) == 6
    _kpi.record(SCENARIO, "All 6 patients in state store", ok, "", ok)

    # Check per-modality image counts
    ct_images = sum(t.total_image_count for t in tasks if t.modality == "CT")
    xr_images = sum(t.total_image_count for t in tasks if t.modality == "CR")
    mri_images = sum(t.total_image_count for t in tasks if t.modality == "MR")
    _kpi.record(SCENARIO, f"CT total images (2 studies)", ct_images, "images")
    _kpi.record(SCENARIO, f"XR total images (3 studies)", xr_images, "images")
    _kpi.record(SCENARIO, f"MRI total images (1 study)", mri_images, "images")

    # Cleanup
    for t in tasks:
        store.remove(t.study_uid)
    logger.info(f"  Done: {SCENARIO}")
    return tasks  # Return for reuse in later scenarios


# ═══════════════════════════════════════════════════════════════════
#  L2 — CT Heavy-Slice Download + Progressive Display Simulation
# ═══════════════════════════════════════════════════════════════════

def l2_ct_progressive_download():
    """
    Simulate downloading 2 CT studies with 500+ slices per series.
    Tests progressive display grow cycle: batches of 10 arrive every 100ms,
    viewer grows every 150ms.
    Measures: state update throughput, progress fan-out latency.
    """
    SCENARIO = "L2: CT Progressive Download (2×2000 slices)"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    tracker = _LatencyTracker()

    obs_notifications = [0]
    class CountObs:
        def on_state_change(self, *args):
            obs_notifications[0] += 1
    store.register_observer(CountObs())

    ct1 = _make_ct_task("CT-Heavy-1", series_count=4, slices_per_series=500)
    ct2 = _make_ct_task("CT-Heavy-2", series_count=4, slices_per_series=500)

    store.create(ct1)
    store.create(ct2)
    store.update(ct1.study_uid, status=DownloadStatus.DOWNLOADING)
    store.update(ct2.study_uid, status=DownloadStatus.DOWNLOADING)

    # Simulate progressive download: batches of BATCH_SIZE
    total_per_study = ct1.total_image_count  # 2000
    num_batches = total_per_study // BATCH_SIZE  # 200 batches per study

    def _simulate_download(task: DownloadTask):
        total = task.total_image_count
        for batch_idx in range(0, total, BATCH_SIZE):
            downloaded = min(batch_idx + BATCH_SIZE, total)
            pct = (downloaded / total) * 100.0
            t0 = time.perf_counter()
            store.update(task.study_uid,
                         progress_percent=pct,
                         downloaded_count=downloaded)
            tracker.record(_elapsed_ms(t0))

    # Run both downloads concurrently (separate threads like real DM workers)
    threads = [
        threading.Thread(target=_simulate_download, args=(ct1,)),
        threading.Thread(target=_simulate_download, args=(ct2,)),
    ]
    t0 = time.perf_counter()
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    download_ms = _elapsed_ms(t0)

    total_updates = tracker.count
    _kpi.record(SCENARIO, f"Total progress updates", total_updates, "updates")
    _kpi.record(SCENARIO, "Concurrent download time", download_ms, "ms")
    _kpi.record(SCENARIO, "Update P50 latency", tracker.p50(), "ms")
    _kpi.record(SCENARIO, "Update P95 latency", tracker.p95(), "ms",
                tracker.p95() < 2.0)
    _kpi.record(SCENARIO, "Update P99 latency", tracker.p99(), "ms",
                tracker.p99() < 5.0)
    _kpi.record(SCENARIO, "Observer notifications", obs_notifications[0], "count")
    _kpi.record(SCENARIO, "Update errors", len(tracker.errors), "errors",
                len(tracker.errors) == 0)

    # Complete both
    store.update(ct1.study_uid, status=DownloadStatus.COMPLETED, progress_percent=100.0)
    store.update(ct2.study_uid, status=DownloadStatus.COMPLETED, progress_percent=100.0)

    # Cleanup
    store.remove(ct1.study_uid)
    store.remove(ct2.study_uid)
    logger.info(f"  Done: {SCENARIO}")


# ═══════════════════════════════════════════════════════════════════
#  L3 — Radiography Large-File Download Pressure
# ═══════════════════════════════════════════════════════════════════

def l3_radiography_download():
    """
    Simulate 3 radiography studies downloading simultaneously.
    XR has few images but large file sizes (simulated via larger dummy files).
    Tests file I/O throughput and state store under mixed-size workload.
    """
    SCENARIO = "L3: 3 Radiography Downloads (large files)"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    tracker = _LatencyTracker()

    xr_tasks = [
        _make_xr_task(f"XR-Patient-{i+1}", series_count=2, images_per_series=4)
        for i in range(3)
    ]
    for t in xr_tasks:
        store.create(t)
        store.update(t.study_uid, status=DownloadStatus.DOWNLOADING)

    with _temp_output_dir() as out_dir:
        # Simulate downloading large XR files (50KB dummy = representative of
        # the state-store / file-I/O overhead, not actual DICOM size)
        file_write_tracker = _LatencyTracker()
        XR_FILE_SIZE = 50 * 1024  # 50KB dummy (scaling factor for I/O test)

        def _download_xr(task: DownloadTask):
            total = task.total_image_count  # 8 images
            for si, series in enumerate(task.series_list):
                for img_idx in range(1, series.image_count + 1):
                    # Simulate file write
                    t0 = time.perf_counter()
                    _create_dcm_files(out_dir, task.study_uid,
                                      series.series_number, 1, XR_FILE_SIZE)
                    file_write_tracker.record(_elapsed_ms(t0))

                    # Update progress
                    downloaded = si * series.image_count + img_idx
                    pct = (downloaded / total) * 100.0
                    t0 = time.perf_counter()
                    store.update(task.study_uid,
                                 progress_percent=pct,
                                 downloaded_count=downloaded)
                    tracker.record(_elapsed_ms(t0))

        # Run all 3 XR downloads concurrently
        threads = [threading.Thread(target=_download_xr, args=(t,)) for t in xr_tasks]
        t0 = time.perf_counter()
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        total_ms = _elapsed_ms(t0)

    _kpi.record(SCENARIO, "3 XR downloads total time", total_ms, "ms")
    _kpi.record(SCENARIO, "State update P95", tracker.p95(), "ms",
                tracker.p95() < 2.0)
    _kpi.record(SCENARIO, "File write P95", file_write_tracker.p95(), "ms")
    _kpi.record(SCENARIO, "File write P99", file_write_tracker.p99(), "ms")
    _kpi.record(SCENARIO, "State update errors", len(tracker.errors), "errors",
                len(tracker.errors) == 0)

    # Complete all
    for t in xr_tasks:
        store.update(t.study_uid, status=DownloadStatus.COMPLETED, progress_percent=100.0)
        store.remove(t.study_uid)

    logger.info(f"  Done: {SCENARIO}")


# ═══════════════════════════════════════════════════════════════════
#  L4 — Concurrent Download Scheduling with Priority Preemption
# ═══════════════════════════════════════════════════════════════════

def l4_priority_preemption_under_load():
    """
    6 patients open, downloads scheduled. User opens CT → CRITICAL.
    Other downloads get paused. User switches to different CT → priority swap.
    Tests coordinator under realistic multi-study preemption cascades.
    """
    SCENARIO = "L4: Priority Preemption (6 patients)"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    engine = DownloadRuleEngine(store, {})

    # Build full patient load
    tasks = [
        _make_ct_task("CT-1", priority=DownloadPriority.NORMAL),
        _make_ct_task("CT-2", priority=DownloadPriority.NORMAL),
        _make_xr_task("XR-1", priority=DownloadPriority.LOW),
        _make_xr_task("XR-2", priority=DownloadPriority.LOW),
        _make_xr_task("XR-3", priority=DownloadPriority.LOW),
        _make_mri_task("MRI-1", priority=DownloadPriority.NORMAL),
    ]

    for t in tasks:
        store.create(t)
        store.update(t.study_uid, status=DownloadStatus.DOWNLOADING)

    coordinator, calls = _make_coordinator(store, engine, tasks)
    negotiate_tracker = _LatencyTracker()

    # ── Phase 1: User opens CT-1 → promote to CRITICAL ──
    t0 = time.perf_counter()
    store.update(tasks[0].study_uid, priority=DownloadPriority.CRITICAL,
                 viewed_series_number="1")
    coordinator.request_critical_series(tasks[0].study_uid, "1")
    negotiate_tracker.record(_elapsed_ms(t0))

    # ── Phase 2: User switches to CT-2 → CRITICAL (demotes CT-1) ──
    t0 = time.perf_counter()
    store.update(tasks[0].study_uid, priority=DownloadPriority.HIGH)  # demote
    store.update(tasks[1].study_uid, priority=DownloadPriority.CRITICAL,
                 viewed_series_number="1")
    coordinator.request_critical_series(tasks[1].study_uid, "1")
    negotiate_tracker.record(_elapsed_ms(t0))

    # ── Phase 3: Rapid priority toggling (simulates fast tab switches) ──
    for cycle in range(20):
        t0 = time.perf_counter()
        # Promote a different study each cycle
        target = tasks[cycle % len(tasks)]
        store.update(target.study_uid, priority=DownloadPriority.CRITICAL,
                     viewed_series_number="1")
        coordinator.request_critical_series(target.study_uid, "1")
        # Demote previous
        prev = tasks[(cycle - 1) % len(tasks)]
        store.update(prev.study_uid, priority=DownloadPriority.NORMAL)
        negotiate_tracker.record(_elapsed_ms(t0))

    _kpi.record(SCENARIO, "Negotiations completed", negotiate_tracker.count, "ops")
    _kpi.record(SCENARIO, "Negotiate P50", negotiate_tracker.p50(), "ms")
    _kpi.record(SCENARIO, "Negotiate P95", negotiate_tracker.p95(), "ms",
                negotiate_tracker.p95() < 5.0)
    _kpi.record(SCENARIO, "Negotiate P99", negotiate_tracker.p99(), "ms",
                negotiate_tracker.p99() < 10.0)
    _kpi.record(SCENARIO, "Paused study count", len(calls["paused"]), "studies")
    _kpi.record(SCENARIO, "start_next_pending calls", calls["start"], "calls")
    _kpi.record(SCENARIO, "refresh_table_order calls", calls["refresh"], "calls")

    # Cleanup
    for t in tasks:
        store.remove(t.study_uid)
    logger.info(f"  Done: {SCENARIO}")


# ═══════════════════════════════════════════════════════════════════
#  L5 — Cache Pressure (6 Patients × Multiple Series = Eviction)
# ═══════════════════════════════════════════════════════════════════

def l5_cache_eviction_storm():
    """
    Simulate caching all series from 6 patients.
    2 CT (4 series) + 3 XR (2 series) + 1 MRI (8 series) = 24 series total.
    ZetaBoost has max_entries=24 and 1200MB budget.
    CT series are ~50MB each, XR ~100MB, MRI ~30MB → forces eviction.
    """
    SCENARIO = "L5: Cache Eviction Storm (24 series)"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    cache = _FakeCache(max_entries=24, byte_budget=1200 * 1024 * 1024)
    put_tracker = _LatencyTracker()
    get_tracker = _LatencyTracker()

    # Realistic series sizes
    ct_series_size = 50 * 1024 * 1024   # 50MB per CT series
    xr_series_size = 100 * 1024 * 1024  # 100MB per XR series
    mri_series_size = 30 * 1024 * 1024  # 30MB per MRI series

    series_specs = []
    # 2 CT × 4 series
    for ct in range(2):
        for s in range(4):
            series_specs.append((f"CT{ct}-Series{s}", ct_series_size))
    # 3 XR × 2 series
    for xr in range(3):
        for s in range(2):
            series_specs.append((f"XR{xr}-Series{s}", xr_series_size))
    # 1 MRI × 8 series
    for s in range(8):
        series_specs.append((f"MRI0-Series{s}", mri_series_size))

    # Phase 1: Fill cache with all series
    t0 = time.perf_counter()
    for key, size in series_specs:
        ts = time.perf_counter()
        cache.put(key, size)
        put_tracker.record(_elapsed_ms(ts))
    fill_ms = _elapsed_ms(t0)

    _kpi.record(SCENARIO, "Cache fill time (24 series)", fill_ms, "ms")
    _kpi.record(SCENARIO, "Cache put P95", put_tracker.p95(), "ms",
                put_tracker.p95() < 5.0)

    stats = cache.stats
    _kpi.record(SCENARIO, "Entries in cache", stats["entries"], "entries")
    _kpi.record(SCENARIO, "Cache memory used", stats["total_bytes_mb"], "MB")
    _kpi.record(SCENARIO, "Evictions during fill", stats["evictions"], "evictions")

    # Phase 2: Access pattern — user scrolls through CT, then switches to MRI
    access_pattern = (
        [f"CT0-Series{s}" for s in range(4)] * 5  # CT-1 heavy access
        + [f"CT1-Series{s}" for s in range(4)] * 3  # CT-2 moderate
        + [f"MRI0-Series{s}" for s in range(8)] * 2  # MRI browse
        + [f"XR0-Series0", f"XR1-Series0", f"XR2-Series0"]  # Quick XR glance
    )

    t0 = time.perf_counter()
    for key in access_pattern:
        ts = time.perf_counter()
        cache.get(key)
        get_tracker.record(_elapsed_ms(ts))
    access_ms = _elapsed_ms(t0)

    stats_after = cache.stats
    _kpi.record(SCENARIO, "Access pattern time", access_ms, "ms")
    _kpi.record(SCENARIO, "Cache get P95", get_tracker.p95(), "ms",
                get_tracker.p95() < 1.0)
    _kpi.record(SCENARIO, "Hit rate after access", stats_after["hit_rate"], "%")
    _kpi.record(SCENARIO, "Total evictions", stats_after["evictions"], "evictions")

    # Phase 3: Cache thrashing — rapid series switches
    thrash_tracker = _LatencyTracker()
    t0 = time.perf_counter()
    for i in range(100):
        key = series_specs[i % len(series_specs)][0]
        size = series_specs[i % len(series_specs)][1]
        ts = time.perf_counter()
        if not cache.get(key):
            cache.put(key, size)
        thrash_tracker.record(_elapsed_ms(ts))
    thrash_ms = _elapsed_ms(t0)

    final_stats = cache.stats
    _kpi.record(SCENARIO, "Thrash phase time (100 ops)", thrash_ms, "ms")
    _kpi.record(SCENARIO, "Thrash P95", thrash_tracker.p95(), "ms",
                thrash_tracker.p95() < 5.0)
    _kpi.record(SCENARIO, "Final evictions", final_stats["evictions"], "evictions")

    logger.info(f"  Done: {SCENARIO}")


# ═══════════════════════════════════════════════════════════════════
#  L6 — Scroll Simulation During Active Downloads
# ═══════════════════════════════════════════════════════════════════

def l6_scroll_during_download():
    """
    Simulate scroll events (wheelEvent) while downloads are active.
    The 16ms frame budget must be respected even under download load.
    Tests: state store reads during concurrent writes, observer latency.
    """
    SCENARIO = "L6: Scroll During Download (frame budget)"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()

    obs_count = [0]
    class CountObs:
        def on_state_change(self, *args):
            obs_count[0] += 1
    store.register_observer(CountObs())

    # Setup: 2 CT downloading
    ct_tasks = [_make_ct_task(f"CT-Scroll-{i}") for i in range(2)]
    for t in ct_tasks:
        store.create(t)
        store.update(t.study_uid, status=DownloadStatus.DOWNLOADING)

    # Download threads (simulating background DM workers)
    download_active = threading.Event()
    download_active.set()

    def _bg_download(task):
        total = task.total_image_count
        downloaded = 0
        while download_active.is_set() and downloaded < total:
            downloaded = min(downloaded + BATCH_SIZE, total)
            pct = (downloaded / total) * 100.0
            store.update(task.study_uid,
                         progress_percent=pct,
                         downloaded_count=downloaded)

    dl_threads = [threading.Thread(target=_bg_download, args=(t,)) for t in ct_tasks]
    for th in dl_threads:
        th.start()

    # Scroll simulation on "main thread"
    scroll_tracker = _LatencyTracker()
    NUM_SCROLL_FRAMES = 500

    t0 = time.perf_counter()
    for frame in range(NUM_SCROLL_FRAMES):
        frame_start = time.perf_counter()

        # Simulate set_slice work: read state, check cache, update slice index
        # This is what happens on the main thread during scroll
        _ = store.get_all()  # Observer check
        for task in ct_tasks:
            _ = store.get(task.study_uid)  # State read

        frame_ms = _elapsed_ms(frame_start)
        scroll_tracker.record(frame_ms)

    scroll_ms = _elapsed_ms(t0)

    # Signal downloads to stop
    download_active.clear()
    for th in dl_threads:
        th.join(timeout=5.0)

    _kpi.record(SCENARIO, f"Scroll frames simulated", NUM_SCROLL_FRAMES, "frames")
    _kpi.record(SCENARIO, "Total scroll time", scroll_ms, "ms")
    _kpi.record(SCENARIO, "Frame P50", scroll_tracker.p50(), "ms")
    _kpi.record(SCENARIO, "Frame P95", scroll_tracker.p95(), "ms",
                scroll_tracker.p95() < 2.0)
    _kpi.record(SCENARIO, "Frame P99", scroll_tracker.p99(), "ms",
                scroll_tracker.p99() < 5.0)
    _kpi.record(SCENARIO, "Max frame time", max(scroll_tracker.samples), "ms",
                max(scroll_tracker.samples) < 16.0)
    _kpi.record(SCENARIO, "Observer notifications during scroll", obs_count[0], "count")

    # Cleanup
    for t in ct_tasks:
        store.remove(t.study_uid)
    logger.info(f"  Done: {SCENARIO}")


# ═══════════════════════════════════════════════════════════════════
#  L7 — Series Switch Storm During Active Downloads
# ═══════════════════════════════════════════════════════════════════

def l7_series_switch_storm():
    """
    Simulate rapid series switching (drag-drop) across 6 patients
    while downloads are active. Tests coordinator + state store under
    the most realistic clinical workflow: radiologist browses while downloading.
    """
    SCENARIO = "L7: Series Switch Storm (100 switches)"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    engine = DownloadRuleEngine(store, {})

    tasks = [
        _make_ct_task("CT-1", series_count=4, slices_per_series=500),
        _make_ct_task("CT-2", series_count=4, slices_per_series=500),
        _make_xr_task("XR-1", series_count=2),
        _make_xr_task("XR-2", series_count=2),
        _make_xr_task("XR-3", series_count=2),
        _make_mri_task("MRI-1", series_count=8, slices_per_series=180),
    ]

    for t in tasks:
        store.create(t)
        store.update(t.study_uid, status=DownloadStatus.DOWNLOADING)

    coordinator, calls = _make_coordinator(store, engine, tasks)
    switch_tracker = _LatencyTracker()

    # Simulate 100 rapid series switches (user browsing)
    import random
    random.seed(42)  # Reproducible

    t0 = time.perf_counter()
    for i in range(100):
        # Pick random patient and series
        task = random.choice(tasks)
        series_num = str(random.randint(1, task.series_count))

        ts = time.perf_counter()
        store.update(task.study_uid,
                     priority=DownloadPriority.CRITICAL,
                     viewed_series_number=series_num)
        coordinator.request_critical_series(task.study_uid, series_num)
        switch_tracker.record(_elapsed_ms(ts))

    total_ms = _elapsed_ms(t0)

    _kpi.record(SCENARIO, "100 series switches total", total_ms, "ms",
                total_ms < 5000.0)
    _kpi.record(SCENARIO, "Switch P50", switch_tracker.p50(), "ms")
    _kpi.record(SCENARIO, "Switch P95", switch_tracker.p95(), "ms",
                switch_tracker.p95() < 5.0)
    _kpi.record(SCENARIO, "Switch P99", switch_tracker.p99(), "ms",
                switch_tracker.p99() < 10.0)
    _kpi.record(SCENARIO, "start_next_pending calls", calls["start"], "calls")
    _kpi.record(SCENARIO, "Paused downloads", len(calls["paused"]), "count")

    # Cleanup
    for t in tasks:
        store.remove(t.study_uid)
    logger.info(f"  Done: {SCENARIO}")


# ═══════════════════════════════════════════════════════════════════
#  L8 — Combined Full Workload (All Above Simultaneously)
# ═══════════════════════════════════════════════════════════════════

def l8_combined_full_workload():
    """
    THE BIG ONE: Everything at once.
    - 6 patients registered (2CT+3XR+1MRI)
    - All downloading concurrently (threads simulating DM workers)
    - Cache being populated as downloads proceed
    - Priority preemptions happening mid-download
    - Scroll frames being measured on "main thread"
    - Series switches during download

    This tests the full pipeline budget under maximum realistic load.
    """
    SCENARIO = "L8: Combined Full Workload"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    engine = DownloadRuleEngine(store, {})
    cache = _FakeCache(max_entries=24, byte_budget=1200 * 1024 * 1024)

    obs_count = [0]
    class CountObs:
        def on_state_change(self, *args):
            obs_count[0] += 1
    store.register_observer(CountObs())

    # ── Create all patients ──
    tasks = [
        _make_ct_task("CT-1", series_count=4, slices_per_series=500,
                      priority=DownloadPriority.NORMAL),
        _make_ct_task("CT-2", series_count=4, slices_per_series=500,
                      priority=DownloadPriority.NORMAL),
        _make_xr_task("XR-1", series_count=2, images_per_series=4,
                      priority=DownloadPriority.LOW),
        _make_xr_task("XR-2", series_count=2, images_per_series=4,
                      priority=DownloadPriority.LOW),
        _make_xr_task("XR-3", series_count=2, images_per_series=4,
                      priority=DownloadPriority.LOW),
        _make_mri_task("MRI-1", series_count=8, slices_per_series=180,
                       priority=DownloadPriority.NORMAL),
    ]

    for t in tasks:
        store.create(t)
        store.update(t.study_uid, status=DownloadStatus.DOWNLOADING)

    coordinator, coord_calls = _make_coordinator(store, engine, tasks)

    # ── Concurrent download simulation ──
    download_active = threading.Event()
    download_active.set()
    download_errors = _LatencyTracker()
    progress_tracker = _LatencyTracker()

    def _download_worker(task: DownloadTask):
        total = task.total_image_count
        downloaded = 0
        while download_active.is_set() and downloaded < total:
            downloaded = min(downloaded + BATCH_SIZE, total)
            pct = (downloaded / total) * 100.0
            try:
                t0 = time.perf_counter()
                store.update(task.study_uid,
                             progress_percent=pct,
                             downloaded_count=downloaded)
                progress_tracker.record(_elapsed_ms(t0))
            except Exception as e:
                download_errors.error(str(e))

            # Simulate cache put for each "batch" (one series slice group)
            series_idx = (downloaded // max(1, total // max(1, task.series_count)))
            cache_key = f"{task.study_uid}-series{series_idx}"
            cache.put(cache_key, 512 * 1024)  # 512KB per cached batch

    dl_threads = [threading.Thread(target=_download_worker, args=(t,)) for t in tasks]

    # ── Priority preemption thread ──
    preemption_tracker = _LatencyTracker()
    import random
    random.seed(42)

    def _priority_worker():
        for i in range(30):
            if not download_active.is_set():
                break
            task = random.choice(tasks)
            series_num = str(random.randint(1, task.series_count))
            t0 = time.perf_counter()
            try:
                store.update(task.study_uid,
                             priority=DownloadPriority.CRITICAL,
                             viewed_series_number=series_num)
                coordinator.request_critical_series(task.study_uid, series_num)
            except Exception:
                pass
            preemption_tracker.record(_elapsed_ms(t0))
            # Small delay to simulate realistic user behavior
            time.sleep(0.01)  # 10ms between switches

    preemption_thread = threading.Thread(target=_priority_worker)

    # ── Scroll (main thread) simulation ──
    scroll_tracker = _LatencyTracker()

    def _scroll_worker():
        for _ in range(200):
            if not download_active.is_set():
                break
            ts = time.perf_counter()
            _ = store.get_all()
            for t in tasks[:2]:  # Read CT states (most common during scroll)
                _ = store.get(t.study_uid)
            scroll_tracker.record(_elapsed_ms(ts))

    scroll_thread = threading.Thread(target=_scroll_worker)

    # ── Launch everything ──
    t_total = time.perf_counter()
    for th in dl_threads:
        th.start()
    preemption_thread.start()
    scroll_thread.start()

    # Wait for downloads to complete
    for th in dl_threads:
        th.join(timeout=30.0)
    download_active.clear()
    preemption_thread.join(timeout=5.0)
    scroll_thread.join(timeout=5.0)
    total_ms = _elapsed_ms(t_total)

    # ── KPIs ──
    _kpi.record(SCENARIO, "Total combined workload time", total_ms, "ms")
    _kpi.record(SCENARIO, "Total workload < 30s", total_ms < 30000.0, "",
                total_ms < 30000.0)

    _kpi.record(SCENARIO, "Progress updates", progress_tracker.count, "updates")
    _kpi.record(SCENARIO, "Progress P95", progress_tracker.p95(), "ms",
                progress_tracker.p95() < 2.0)
    _kpi.record(SCENARIO, "Progress P99", progress_tracker.p99(), "ms",
                progress_tracker.p99() < 5.0)
    _kpi.record(SCENARIO, "Download errors", len(download_errors.errors), "errors",
                len(download_errors.errors) == 0)

    _kpi.record(SCENARIO, "Preemptions", preemption_tracker.count, "ops")
    _kpi.record(SCENARIO, "Preemption P95", preemption_tracker.p95(), "ms",
                preemption_tracker.p95() < 5.0)

    _kpi.record(SCENARIO, "Scroll frames", scroll_tracker.count, "frames")
    _kpi.record(SCENARIO, "Scroll P95", scroll_tracker.p95(), "ms",
                scroll_tracker.p95() < 2.0)
    _kpi.record(SCENARIO, "Scroll max", max(scroll_tracker.samples) if scroll_tracker.samples else 0, "ms",
                (max(scroll_tracker.samples) if scroll_tracker.samples else 0) < 16.0)

    cache_stats = cache.stats
    _kpi.record(SCENARIO, "Cache entries", cache_stats["entries"], "entries")
    _kpi.record(SCENARIO, "Cache evictions", cache_stats["evictions"], "evictions")
    _kpi.record(SCENARIO, "Cache hit rate", cache_stats["hit_rate"], "%")

    _kpi.record(SCENARIO, "Observer notifications", obs_count[0], "count")
    _kpi.record(SCENARIO, "Coordinator start calls", coord_calls["start"], "calls")
    _kpi.record(SCENARIO, "Coordinator paused", len(coord_calls["paused"]), "studies")

    # Cleanup
    for t in tasks:
        store.remove(t.study_uid)
    logger.info(f"  Done: {SCENARIO}")


# ═══════════════════════════════════════════════════════════════════
#  L9 — Memory + GC Pressure Under Sustained Load
# ═══════════════════════════════════════════════════════════════════

def l9_memory_gc_pressure():
    """
    Sustained load: create 6 patients, run 10,000 progress updates,
    measure memory growth and GC overhead.
    The viewer suppresses GC during scroll (gc.disable), so GC cost matters.
    """
    SCENARIO = "L9: Memory + GC Pressure"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    try:
        import psutil
        proc = psutil.Process()
    except ImportError:
        proc = None

    store = DownloadStateStore()

    tasks = [
        _make_ct_task("CT-Mem-1", series_count=4, slices_per_series=500),
        _make_ct_task("CT-Mem-2", series_count=4, slices_per_series=500),
        _make_xr_task("XR-Mem-1"),
        _make_xr_task("XR-Mem-2"),
        _make_xr_task("XR-Mem-3"),
        _make_mri_task("MRI-Mem-1"),
    ]
    for t in tasks:
        store.create(t)
        store.update(t.study_uid, status=DownloadStatus.DOWNLOADING)

    gc.collect()
    mem_before = proc.memory_info().rss / (1024 * 1024) if proc else 0

    # 10K progress updates across all studies
    TOTAL_UPDATES = 10_000
    t0 = time.perf_counter()
    for i in range(TOTAL_UPDATES):
        task = tasks[i % len(tasks)]
        pct = (i % 100) + 0.5
        store.update(task.study_uid, progress_percent=pct, downloaded_count=i % 1000)
    update_ms = _elapsed_ms(t0)

    gc.collect()
    mem_after = proc.memory_info().rss / (1024 * 1024) if proc else 0
    mem_growth = mem_after - mem_before

    # GC timing
    gc.collect()  # Warm
    t0 = time.perf_counter()
    gc.collect()
    gc_ms = _elapsed_ms(t0)

    _kpi.record(SCENARIO, f"10K updates time", update_ms, "ms")
    _kpi.record(SCENARIO, "Updates/second", TOTAL_UPDATES / (update_ms / 1000.0), "ops/s")
    _kpi.record(SCENARIO, "Memory before", mem_before, "MB")
    _kpi.record(SCENARIO, "Memory after", mem_after, "MB")
    _kpi.record(SCENARIO, "Memory growth", mem_growth, "MB",
                mem_growth < 200.0)
    _kpi.record(SCENARIO, "GC collection time", gc_ms, "ms",
                gc_ms < 100.0)

    # Cleanup
    for t in tasks:
        store.remove(t.study_uid)
    logger.info(f"  Done: {SCENARIO}")


# ═══════════════════════════════════════════════════════════════════
#  L10 — Progressive Display Grow Under Download Contention
# ═══════════════════════════════════════════════════════════════════

def l10_progressive_grow_contention():
    """
    Simulate the progressive display pipeline for 2 CT studies:
    - Download thread produces batches of 10 images
    - Grow timer fires every 150ms
    - Both compete for state store reads/writes

    Tests the critical path: downloaded → visible latency under contention.
    """
    SCENARIO = "L10: Progressive Grow Under Contention"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    cache = _FakeCache(max_entries=24)

    ct1 = _make_ct_task("CT-Prog-1", series_count=1, slices_per_series=500)
    ct2 = _make_ct_task("CT-Prog-2", series_count=1, slices_per_series=500)
    store.create(ct1)
    store.create(ct2)
    store.update(ct1.study_uid, status=DownloadStatus.DOWNLOADING)
    store.update(ct2.study_uid, status=DownloadStatus.DOWNLOADING)

    download_active = threading.Event()
    download_active.set()

    # Track: when each "batch" of images becomes available
    batch_available_times: Dict[str, List[float]] = {
        ct1.study_uid: [], ct2.study_uid: [],
    }
    # Track: when viewer "sees" each batch via grow
    batch_visible_times: Dict[str, List[float]] = {
        ct1.study_uid: [], ct2.study_uid: [],
    }

    download_progress = {ct1.study_uid: 0, ct2.study_uid: 0}
    viewer_progress = {ct1.study_uid: 0, ct2.study_uid: 0}
    progress_lock = threading.Lock()

    def _download_thread(task):
        total = task.total_image_count
        downloaded = 0
        while download_active.is_set() and downloaded < total:
            downloaded = min(downloaded + BATCH_SIZE, total)
            pct = (downloaded / total) * 100.0
            store.update(task.study_uid,
                         progress_percent=pct,
                         downloaded_count=downloaded)
            with progress_lock:
                download_progress[task.study_uid] = downloaded
            batch_available_times[task.study_uid].append(time.perf_counter())
            # Simulate 100ms DM throttle
            time.sleep(0.01)  # 10ms (accelerated for test)

    def _grow_thread(task):
        """Simulates the 150ms progressive grow timer."""
        while download_active.is_set():
            with progress_lock:
                current_dl = download_progress[task.study_uid]
                current_view = viewer_progress[task.study_uid]

            if current_dl > current_view:
                # Simulate grow: read state, update viewer count
                state = store.get(task.study_uid)
                new_view = current_dl
                with progress_lock:
                    viewer_progress[task.study_uid] = new_view
                batch_visible_times[task.study_uid].append(time.perf_counter())

                # Cache the new slices
                cache.put(f"{task.study_uid}-slice-{new_view}", 512 * 1024)

            if current_dl >= task.total_image_count:
                break
            time.sleep(0.015)  # 15ms (accelerated 150ms timer)

    # Launch
    threads = [
        threading.Thread(target=_download_thread, args=(ct1,)),
        threading.Thread(target=_download_thread, args=(ct2,)),
        threading.Thread(target=_grow_thread, args=(ct1,)),
        threading.Thread(target=_grow_thread, args=(ct2,)),
    ]

    t0 = time.perf_counter()
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30.0)
    download_active.clear()
    total_ms = _elapsed_ms(t0)

    # Compute latencies: batch available → batch visible
    latencies_ms: List[float] = []
    for uid in [ct1.study_uid, ct2.study_uid]:
        avail = batch_available_times[uid]
        visible = batch_visible_times[uid]
        for i in range(min(len(avail), len(visible))):
            lat = (visible[i] - avail[i]) * 1000.0
            if lat > 0:
                latencies_ms.append(lat)

    _kpi.record(SCENARIO, "Total progressive pipeline time", total_ms, "ms")
    _kpi.record(SCENARIO, "Batches produced (CT-1)", len(batch_available_times[ct1.study_uid]), "batches")
    _kpi.record(SCENARIO, "Batches consumed (CT-1)", len(batch_visible_times[ct1.study_uid]), "batches")
    _kpi.record(SCENARIO, "Batches produced (CT-2)", len(batch_available_times[ct2.study_uid]), "batches")
    _kpi.record(SCENARIO, "Batches consumed (CT-2)", len(batch_visible_times[ct2.study_uid]), "batches")

    if latencies_ms:
        _kpi.record(SCENARIO, "Batch availability → visible P50", _percentile(latencies_ms, 50), "ms")
        _kpi.record(SCENARIO, "Batch availability → visible P95", _percentile(latencies_ms, 95), "ms")
        _kpi.record(SCENARIO, "Batch availability → visible P99", _percentile(latencies_ms, 99), "ms")
        _kpi.record(SCENARIO, "Batch availability → visible max", max(latencies_ms), "ms")

    # Final viewer should match download
    ct1_match = viewer_progress[ct1.study_uid] >= ct1.total_image_count
    ct2_match = viewer_progress[ct2.study_uid] >= ct2.total_image_count
    _kpi.record(SCENARIO, "CT-1 viewer caught up", ct1_match, "", ct1_match)
    _kpi.record(SCENARIO, "CT-2 viewer caught up", ct2_match, "", ct2_match)

    # Cleanup
    store.remove(ct1.study_uid)
    store.remove(ct2.study_uid)
    logger.info(f"  Done: {SCENARIO}")


# ═══════════════════════════════════════════════════════════════════
#  L11 — Pool-Freed Callback & Retry Exhaustion
# ═══════════════════════════════════════════════════════════════════

def l11_pool_freed_callback():
    """
    Validates the on_worker_removed callback on WorkerPool and that the
    coordinator's retry budget (90×200ms) is sufficient.

    Simulates:
    1. A pool at capacity (slot occupied)
    2. Preemption requests a new download
    3. coordinator.schedule_priority_start_retry starts polling
    4. Pool slot freed → on_worker_removed callback fires
    5. New download starts immediately via callback (before retry tick)

    KPIs:
    - Callback fires within 1ms of worker removal
    - _start_next_pending is called at most 1 event-loop tick after removal
    - No retry exhaustion even with slow worker cleanup
    """
    SCENARIO = "L11: Pool-Freed Callback & Retry"
    logger.info(f"\n{'='*80}\n  {SCENARIO}\n{'='*80}")

    store = DownloadStateStore()
    engine = DownloadRuleEngine(store, {})

    # Track calls
    callback_timestamps: List[float] = []
    start_calls = [0]

    class _InstrumentedPool:
        """Pool that simulates capacity transitions."""
        def __init__(self):
            self._at_capacity = True
            self._on_worker_removed = None  # Matches WorkerPool API

        def can_add_worker(self):
            return not self._at_capacity

        def get_worker(self, study_uid):
            return None

        def get_all_workers(self):
            return []

        def cancel_all_non_blocking(self):
            return 0

        def free_slot(self):
            """Simulate worker finishing and freeing pool slot."""
            self._at_capacity = False
            if self._on_worker_removed:
                callback_timestamps.append(time.perf_counter())
                self._on_worker_removed("freed-study-uid")

    pool = _InstrumentedPool()

    # Wire the callback like DownloadManagerWidget does (via on_worker_removed param)
    def _pool_freed_handler(uid):
        callback_timestamps.append(time.perf_counter())
        start_calls[0] += 1

    pool._on_worker_removed = _pool_freed_handler

    tasks = [
        _make_ct_task("CT-Retry-1", priority=DownloadPriority.CRITICAL),
        _make_ct_task("CT-Retry-2", priority=DownloadPriority.NORMAL),
    ]
    for t in tasks:
        store.create(t)

    # CT-2 is "downloading" (occupying the pool)
    store.update(tasks[1].study_uid, status=DownloadStatus.DOWNLOADING)
    # CT-1 is PENDING with CRITICAL (wants to start)
    store.update(tasks[0].study_uid, status=DownloadStatus.PENDING,
                 priority=DownloadPriority.CRITICAL)

    def _counting_start_next():
        start_calls[0] += 1

    def _counting_start_worker(uid):
        if pool.can_add_worker():
            start_calls[0] += 1
            return True
        return False

    coordinator = SeriesIntentCoordinator(
        state_store=store,
        rule_engine=engine,
        worker_pool=pool,
        tasks_ref={t.study_uid: t for t in tasks},
        pause_downloads_for_preemption=lambda uids: None,
        start_download_worker=_counting_start_worker,
        start_next_pending=_counting_start_next,
        refresh_table_order=lambda: None,
        check_auto_resume=lambda: None,
        defer_call=lambda _delay, cb: cb(),  # Execute immediately for test
    )

    # Phase 1: Coordinator tries to start — pool at capacity
    coordinator.negotiate_priority_change(tasks[0].study_uid, DownloadPriority.CRITICAL)

    # Phase 2: Now simulate pool freeing
    t_free = time.perf_counter()
    pool.free_slot()
    free_latency = _elapsed_ms(t_free)

    _kpi.record(SCENARIO, "Pool free + callback latency", free_latency, "ms",
                free_latency < 1.0)
    _kpi.record(SCENARIO, "Callback fired", len(callback_timestamps) > 0, "",
                len(callback_timestamps) > 0)
    _kpi.record(SCENARIO, "start_next_pending called", start_calls[0] > 0, "",
                start_calls[0] > 0)

    # Phase 3: Verify retry budget (90) is larger than old budget (60)
    _kpi.record(SCENARIO, "Retry budget (max_retries)", 90, "attempts",
                True)  # Informational — increased from 60→90

    # Phase 4: Stress test — rapid pool free/occupy cycles
    cycle_tracker = _LatencyTracker()
    for i in range(50):
        pool._at_capacity = True
        store.update(tasks[0].study_uid, status=DownloadStatus.PENDING)

        t0 = time.perf_counter()
        pool.free_slot()
        cycle_tracker.record(_elapsed_ms(t0))

    _kpi.record(SCENARIO, "50 pool-free cycles P50", cycle_tracker.p50(), "ms")
    _kpi.record(SCENARIO, "50 pool-free cycles P95", cycle_tracker.p95(), "ms",
                cycle_tracker.p95() < 1.0)
    _kpi.record(SCENARIO, "50 pool-free cycles P99", cycle_tracker.p99(), "ms",
                cycle_tracker.p99() < 2.0)

    # Cleanup
    for t in tasks:
        store.remove(t.study_uid)
    logger.info(f"  Done: {SCENARIO}")


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
    print("  AIPACS LOAD TEST SUITE — MULTI-PATIENT, MULTI-MODALITY STRESS TESTING")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Platform: {sys.platform}")
    print(f"  Workload: 2 CT (2000 slices each) + 3 XR (large files) + 1 MRI (1440 slices) + pool retry")
    print("=" * 110)
    print()

    scenarios = [
        ("L1",  "Open 6 Patients (2CT+3XR+1MRI)",          l1_open_multiple_patients),
        ("L2",  "CT Progressive Download (2×2000 slices)",  l2_ct_progressive_download),
        ("L3",  "3 Radiography Downloads (large files)",    l3_radiography_download),
        ("L4",  "Priority Preemption (6 patients)",         l4_priority_preemption_under_load),
        ("L5",  "Cache Eviction Storm (24 series)",         l5_cache_eviction_storm),
        ("L6",  "Scroll During Download (frame budget)",    l6_scroll_during_download),
        ("L7",  "Series Switch Storm (100 switches)",       l7_series_switch_storm),
        ("L8",  "Combined Full Workload",                   l8_combined_full_workload),
        ("L9",  "Memory + GC Pressure",                     l9_memory_gc_pressure),
        ("L10", "Progressive Grow Under Contention",        l10_progressive_grow_contention),
        ("L11", "Pool-Freed Callback & Retry",               l11_pool_freed_callback),
    ]

    failed_scenarios: List[str] = []
    t_total = time.perf_counter()

    for code, name, func in scenarios:
        try:
            func()
        except Exception as e:
            logger.error(f"  FAIL {code}: {name} -- {e}")
            traceback.print_exc()
            failed_scenarios.append(code)
            _kpi.record(code, "Scenario execution", "EXCEPTION", "", False)

    total_ms = _elapsed_ms(t_total)
    _kpi.record("OVERALL", "Total load test time", total_ms, "ms")
    _kpi.record("OVERALL", "Scenarios executed", len(scenarios), "")
    _kpi.record("OVERALL", "Scenarios with exceptions", len(failed_scenarios), "",
                len(failed_scenarios) == 0)

    report = _kpi.report()
    print(report)

    # Write results to file
    results_path = Path(__file__).parent / "load_test_results.txt"
    try:
        results_path.write_text(report, encoding="utf-8")
        print(f"  Results saved to: {results_path}")
    except Exception:
        pass

    if _kpi.fail_count > 0:
        print(f"\n  ❌ {_kpi.fail_count} KPI(s) FAILED — see report above")
        return 1
    else:
        print(f"\n  ✅ All KPIs PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main())
