"""
B2.5 Performance Scenario Helpers
==================================
Reusable helpers for concurrent-load KPI scenario tests.

Provides:
- GIL contention simulator (background pydicom.dcmread on synthetic data)
- CPU load simulator (numpy work in background threads)
- Process-level CPU/RSS sampler
- Scroll pattern generators
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))


# ── Synthetic DICOM factory ──────────────────────────────────────────────────

def make_dicom_series_on_disk(
    out_dir: Path,
    n: int = 50,
    rows: int = 64,
    cols: int = 64,
) -> List[Path]:
    """Write *n* synthetic DICOM files into *out_dir*. Returns file list."""
    out_dir.mkdir(parents=True, exist_ok=True)
    series_uid = generate_uid()
    study_uid = generate_uid()
    files: List[Path] = []
    for i in range(n):
        ds = FileDataset(None, {}, preamble=b"\x00" * 128)
        ds.file_meta = Dataset()
        ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
        ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.PatientName = "Perf^Test"
        ds.PatientID = "PERF001"
        ds.PatientBirthDate = "19800101"
        ds.PatientSex = "M"
        ds.StudyInstanceUID = study_uid
        ds.StudyDate = "20260414"
        ds.StudyTime = "120000"
        ds.AccessionNumber = "PERF001"
        ds.InstitutionName = "Test"
        ds.SeriesInstanceUID = series_uid
        ds.SeriesNumber = 1
        ds.Modality = "CT"
        ds.SeriesDescription = "PerfTest"
        ds.SOPInstanceUID = generate_uid()
        ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
        ds.InstanceNumber = i + 1
        ds.ImagePositionPatient = [0.0, 0.0, float(i * 3.0)]
        ds.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        ds.PixelSpacing = [0.9765625, 0.9765625]
        ds.SliceThickness = 3.0
        ds.SpacingBetweenSlices = 3.0
        ds.Rows = rows
        ds.Columns = cols
        ds.PixelRepresentation = 0
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.RescaleSlope = 1.0
        ds.RescaleIntercept = -1024.0
        ds.WindowWidth = 400.0
        ds.WindowCenter = 40.0
        rng = np.random.RandomState(42 + i)
        px = rng.randint(0, 3000, size=(rows, cols), dtype=np.uint16)
        ds.PixelData = px.tobytes()
        ds.is_implicit_VR = False
        ds.is_little_endian = True
        p = out_dir / f"Instance_{i + 1:04d}.dcm"
        pydicom.dcmwrite(str(p), ds)
        files.append(p)
    return files


# ── GIL contention simulator ─────────────────────────────────────────────────

class GILContentionSimulator:
    """Run background pydicom.dcmread in threads to simulate GIL contention.

    This replicates the real-world scenario: LW2D decode workers + main thread
    competing for GIL via pydicom.dcmread.
    """

    def __init__(self, dicom_files: List[Path], workers: int = 4):
        self._files = dicom_files
        self._workers = workers
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self._decode_count = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        self._stop.clear()
        self._decode_count = 0
        for i in range(self._workers):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"GILSim-{i}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)

    def stop(self) -> int:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5.0)
        self._threads.clear()
        return self._decode_count

    def _worker_loop(self) -> None:
        idx = 0
        n = len(self._files)
        while not self._stop.is_set():
            try:
                pydicom.dcmread(str(self._files[idx % n]), force=True)
                with self._lock:
                    self._decode_count += 1
            except Exception:
                pass
            idx += 1


# ── CPU load simulator ────────────────────────────────────────────────────────

class CPULoadSimulator:
    """Run numpy computation in background threads to simulate CPU pressure."""

    def __init__(self, workers: int = 2, array_size: int = 512):
        self._workers = workers
        self._size = array_size
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []

    def start(self) -> None:
        self._stop.clear()
        for i in range(self._workers):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"CPUSim-{i}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5.0)
        self._threads.clear()

    def _worker_loop(self) -> None:
        rng = np.random.RandomState(42)
        while not self._stop.is_set():
            a = rng.random((self._size, self._size)).astype(np.float32)
            _ = np.dot(a, a)  # releases GIL during BLAS


# ── Process-level sampler ─────────────────────────────────────────────────────

class ProcessSampler:
    """Sample CPU% and RSS at regular intervals using psutil."""

    def __init__(self, interval_s: float = 0.5):
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cpu_samples: List[float] = []
        self._rss_mb_samples: List[float] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        try:
            import psutil  # noqa: F401
        except ImportError:
            return  # graceful degradation without psutil
        self._stop.clear()
        self._cpu_samples.clear()
        self._rss_mb_samples.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ProcSampler")
        self._thread.start()

    def stop(self) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        with self._lock:
            from modules.viewer.fast.perf_metrics import _percentile
            return {
                "cpu_p50_pct": round(_percentile(self._cpu_samples, 50), 1),
                "cpu_p95_pct": round(_percentile(self._cpu_samples, 95), 1),
                "cpu_max_pct": round(max(self._cpu_samples) if self._cpu_samples else 0.0, 1),
                "rss_start_mb": round(self._rss_mb_samples[0], 1) if self._rss_mb_samples else 0.0,
                "rss_end_mb": round(self._rss_mb_samples[-1], 1) if self._rss_mb_samples else 0.0,
                "rss_growth_mb": round(
                    self._rss_mb_samples[-1] - self._rss_mb_samples[0], 1
                ) if len(self._rss_mb_samples) >= 2 else 0.0,
                "samples": len(self._cpu_samples),
            }

    def _loop(self) -> None:
        import psutil
        proc = psutil.Process(os.getpid())
        proc.cpu_percent()  # prime the counter
        while not self._stop.wait(self._interval):
            try:
                cpu = proc.cpu_percent()
                rss_mb = proc.memory_info().rss / (1024 * 1024)
                with self._lock:
                    self._cpu_samples.append(cpu)
                    self._rss_mb_samples.append(rss_mb)
            except Exception:
                pass


# ── Scroll pattern generators ────────────────────────────────────────────────

def scroll_forward(n_slices: int) -> List[int]:
    """Sequential forward: 0, 1, 2, ..., n-1."""
    return list(range(n_slices))


def scroll_rapid_burst(n_slices: int, burst_length: int = 50) -> List[int]:
    """Fast forward burst then stop."""
    return list(range(min(burst_length, n_slices)))


def scroll_direction_reversal(n_slices: int, cycles: int = 10, segment: int = 10) -> List[int]:
    """Alternate forward/backward every *segment* slices for *cycles*."""
    pattern: List[int] = []
    pos = n_slices // 2
    for c in range(cycles):
        direction = 1 if c % 2 == 0 else -1
        for _ in range(segment):
            pos = max(0, min(n_slices - 1, pos + direction))
            pattern.append(pos)
    return pattern


def scroll_random(n_slices: int, count: int = 200, seed: int = 42) -> List[int]:
    """Random access pattern."""
    import random
    rng = random.Random(seed)
    return [rng.randint(0, n_slices - 1) for _ in range(count)]


def scroll_stack_drag(n_slices: int, steps_per_event: int = 4, events: int = 30) -> List[int]:
    """Simulate stack-drag: multiple ±1 steps per mouse-move event.

    Returns a list of slice indices that a stack-drag would visit when
    emitting *steps_per_event* individual ±1 signals per mouse-move event,
    over *events* total mouse-move events.
    """
    pattern: List[int] = []
    pos = 0
    for _ in range(events):
        for _ in range(steps_per_event):
            pos = min(n_slices - 1, pos + 1)
            pattern.append(pos)
    return pattern
