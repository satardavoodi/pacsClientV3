"""F1.1 — Pixel-hash quality gate for FAST viewer overlap optimization.

This test is the mandatory **image-quality safety net** that gates every
behaviour-changing step in phases F3–F9 of the overlap performance plan
(see ``untitled:plan-fastViewerOverlap100PercentImprovement.prompt.md``).

Strategy
--------
For each combination of (filter_enabled × photometric_interpretation) we:
  1. Build a deterministic synthetic 10-slice 64×64 DICOM series on disk.
  2. Open it through the production ``Lightweight2DPipeline`` with
     ``fast_interaction=False`` (settled rendering — the user-perceived final
     image, never an in-flight surrogate).
  3. Render every slice and compute ``sha256(bytes(qimage.constBits()))``.
  4. Compare the resulting hash list against a golden JSON written under
     ``tests/viewer/golden/``.

The golden file is captured exactly once per case via the ``--capture-golden``
pytest flag (see ``tests/viewer/conftest.py``). Any later code change that
alters a pixel will fail this test and BLOCK the merge.

Cases
-----
* ``filter_off_mono2``: MONOCHROME2, OpenCV unsharp filter disabled
* ``filter_on_mono2`` : MONOCHROME2, OpenCV unsharp filter enabled
* ``filter_off_mono1``: MONOCHROME1, OpenCV unsharp filter disabled
* ``filter_on_mono1`` : MONOCHROME1, OpenCV unsharp filter enabled

Surrogate (in-flight) frames are validated by F1.2 (a separate test, ≥99%
match tolerance because surrogates are by design an approximation).

Plan reference: F1.1.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pytest

# ── Headless Qt (avoid creating a real window) ───────────────────────────────
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

N_SLICES = 10
ROWS = 64
COLS = 64


# ── Case matrix ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Case:
    case_id: str
    filter_enabled: bool
    photometric: str  # "MONOCHROME1" | "MONOCHROME2"

    @property
    def golden_path(self) -> Path:
        return GOLDEN_DIR / f"overlap_pixel_{self.case_id}.json"


CASES: List[Case] = [
    Case("filter_off_mono2", filter_enabled=False, photometric="MONOCHROME2"),
    Case("filter_on_mono2", filter_enabled=True, photometric="MONOCHROME2"),
    Case("filter_off_mono1", filter_enabled=False, photometric="MONOCHROME1"),
    Case("filter_on_mono1", filter_enabled=True, photometric="MONOCHROME1"),
]


# ── Synthetic DICOM factory (deterministic, photometric-aware) ───────────────

def _make_series(out_dir: Path, photometric: str) -> List[Path]:
    """Write a deterministic ``N_SLICES``-image DICOM series.

    Pixel data is derived from a fixed seed (per-slice index) so the same
    series is byte-identical across machines and runs. ``RescaleSlope`` and
    ``RescaleIntercept`` exercise the slope/intercept code path.
    """
    import pydicom
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    out_dir.mkdir(parents=True, exist_ok=True)
    # Deterministic UIDs — identical across runs/machines for this test.
    series_uid = "1.2.826.0.1.3680043.8.498.10000000000000000000000000000001"
    study_uid = "1.2.826.0.1.3680043.8.498.20000000000000000000000000000001"

    files: List[Path] = []
    for i in range(N_SLICES):
        ds = FileDataset(None, {}, preamble=b"\x00" * 128)
        ds.file_meta = Dataset()
        ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
        # Deterministic SOP Instance UID (only the suffix varies by index).
        ds.file_meta.MediaStorageSOPInstanceUID = (
            f"1.2.826.0.1.3680043.8.498.30000000000000000000000000{i:06d}"
        )
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.PatientName = "PixelHash^Test"
        ds.PatientID = "PIX001"
        ds.PatientBirthDate = "19800101"
        ds.PatientSex = "M"
        ds.StudyInstanceUID = study_uid
        ds.StudyDate = "20260428"
        ds.StudyTime = "120000"
        ds.AccessionNumber = "PIX001"
        ds.SeriesInstanceUID = series_uid
        ds.SeriesNumber = 1
        ds.Modality = "CT"
        ds.SeriesDescription = "PixelHashTest"
        ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
        ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
        ds.InstanceNumber = i + 1
        ds.ImagePositionPatient = [0.0, 0.0, float(i * 3.0)]
        ds.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        ds.PixelSpacing = [0.9765625, 0.9765625]
        ds.SliceThickness = 3.0
        ds.SpacingBetweenSlices = 3.0
        ds.Rows = ROWS
        ds.Columns = COLS
        ds.PixelRepresentation = 0
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = photometric
        ds.RescaleSlope = 1.0
        ds.RescaleIntercept = -1024.0
        ds.WindowWidth = 400.0
        ds.WindowCenter = 40.0
        rng = np.random.RandomState(1000 + i)
        px = rng.randint(0, 3000, size=(ROWS, COLS), dtype=np.uint16)
        ds.PixelData = px.tobytes()
        ds.is_implicit_VR = False
        ds.is_little_endian = True
        p = out_dir / f"Instance_{i + 1:04d}.dcm"
        pydicom.dcmwrite(str(p), ds)
        files.append(p)
    return files


# ── Hash extraction ──────────────────────────────────────────────────────────

def _qimage_sha256(qimage) -> str:
    """SHA-256 of the raw QImage backing buffer."""
    raw = bytes(qimage.constBits())
    return hashlib.sha256(raw).hexdigest()


def _capture_settled_hashes(series_dir: Path, case: Case) -> Tuple[List[str], Dict[str, object]]:
    """Open the series, render all slices in settled mode, return per-slice hashes."""
    from modules.viewer.fast.lightweight_2d_pipeline import (
        Lightweight2DPipeline,
        PipelineConfig,
    )

    cfg = PipelineConfig(
        pixel_cache_size=N_SLICES * 2,
        frame_cache_size=N_SLICES * 2,
        prefetch_radius=0,            # disable background work for determinism
        prefetch_workers=1,
        opencv_filter_enabled=case.filter_enabled,
    )
    pipeline = Lightweight2DPipeline(config=cfg)
    try:
        pipeline.open_series(str(series_dir))
        # Settled rendering — never the surrogate path.
        pipeline.set_fast_interaction(False)

        hashes: List[str] = []
        meta_first = None
        for idx in range(N_SLICES):
            frame = pipeline.get_rendered_frame(idx)
            assert frame is not None, f"No frame for idx={idx}"
            assert frame.qimage is not None, f"No QImage for idx={idx}"
            assert frame.width == COLS, f"Width drift at idx={idx}: {frame.width}"
            assert frame.height == ROWS, f"Height drift at idx={idx}: {frame.height}"
            if meta_first is None:
                meta_first = {
                    "width": frame.width,
                    "height": frame.height,
                    "photometric": frame.photometric,
                    "window_width": frame.window_width,
                    "window_center": frame.window_center,
                }
            hashes.append(_qimage_sha256(frame.qimage))
        return hashes, (meta_first or {})
    finally:
        try:
            pipeline.shutdown()
        except Exception:
            pass


# ── Test entry point ─────────────────────────────────────────────────────────

@pytest.fixture
def capture_golden(request) -> bool:
    """True when ``--capture-golden`` is passed (or AIPACS_CAPTURE_GOLDEN=1)."""
    flag = bool(request.config.getoption("--capture-golden"))
    env = os.environ.get("AIPACS_CAPTURE_GOLDEN", "").strip() == "1"
    return flag or env


@pytest.mark.parametrize(
    "case",
    CASES,
    ids=[c.case_id for c in CASES],
)
def test_overlap_pixel_quality_settled(case: Case, tmp_path: Path, capture_golden: bool):
    """Settled-frame pixel hashes must match the golden file 100%.

    F1.1 contract:
      * In ``--capture-golden`` mode, write the golden JSON and pass.
      * Otherwise, load the golden JSON and require an EXACT match.
      * Missing golden file is a hard failure (with capture instructions).
    """
    series_dir = tmp_path / "series"
    _make_series(series_dir, case.photometric)

    hashes, meta = _capture_settled_hashes(series_dir, case)

    payload = {
        "schema_version": 1,
        "case_id": case.case_id,
        "filter_enabled": case.filter_enabled,
        "photometric": case.photometric,
        "n_slices": N_SLICES,
        "rows": ROWS,
        "cols": COLS,
        "rendered_meta_first": meta,
        "hashes": hashes,
    }

    if capture_golden:
        case.golden_path.parent.mkdir(parents=True, exist_ok=True)
        case.golden_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return

    if not case.golden_path.exists():
        pytest.fail(
            f"Golden file missing for case '{case.case_id}'.\n"
            f"Capture it with:\n"
            f"  .venv\\Scripts\\python.exe -m pytest "
            f"tests/viewer/test_overlap_pixel_quality.py "
            f"--capture-golden -v\n"
            f"Expected path: {case.golden_path}"
        )

    golden = json.loads(case.golden_path.read_text(encoding="utf-8"))
    assert golden["case_id"] == case.case_id
    assert golden["filter_enabled"] == case.filter_enabled
    assert golden["photometric"] == case.photometric
    assert golden["n_slices"] == N_SLICES
    assert golden["rows"] == ROWS
    assert golden["cols"] == COLS

    expected = list(golden["hashes"])
    actual = list(hashes)
    if expected != actual:
        diff_idx = [i for i, (a, b) in enumerate(zip(expected, actual)) if a != b]
        pytest.fail(
            f"Pixel-hash mismatch for case '{case.case_id}': "
            f"{len(diff_idx)} / {N_SLICES} slices differ "
            f"(indices {diff_idx[:5]}{'...' if len(diff_idx) > 5 else ''}).\n"
            f"Image quality has changed. Either:\n"
            f"  (a) the change was unintended — REVERT IT, or\n"
            f"  (b) the change was intentional — re-capture goldens with "
            f"--capture-golden and document the reason."
        )
