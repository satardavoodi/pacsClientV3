"""F0.4 — Synthetic overlap headless runner.

Reproduces the "downloading + stack-drag" scenario without a Qt window or a
real download manager, so the ``[OVERLAP_SCENARIO]`` log tag (F2.1) can be
exercised on any developer machine without human input. The output JSON is the
synthetic baseline ``overlap_baseline_v0_synthetic.json``.

Limitations (documented per plan F0.4):

* Pixel data is generated up-front and the entire series is on disk before
  rendering starts. The "drip-feed" of arrival is simulated by toggling the
  ZetaBoost ``_GLOBAL_DOWNLOAD_ACTIVE`` flag for the duration of the run and
  by sweeping the slice index in the same pattern a stack-drag would, NOT by
  hiding files from the pipeline. Real network latency and disk-flush
  ordering are out of scope.
* All renders are driven synchronously through ``get_rendered_frame``; we do
  not spin a Qt event loop. The numbers reproduce the cache/surrogate/decode
  *distribution*, not the wall-clock event-loop responsiveness of a live UI.
* Determinism is best-effort: pixel data is fixed-seed, but
  ``decode_ms`` / ``wl_ms`` / ``total_ms`` depend on the host CPU. Treat the
  synthetic baseline as a smoke-level signal — it should land within ~30%
  of human-captured baselines on the same machine.

Plan reference: F0.4.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Headless Qt — avoid creating a real window when QtSliceViewer touches QImage.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── Synthetic DICOM factory (adapted from tests/viewer/test_overlap_pixel_quality.py) ──

def _make_synthetic_overlap_series(
    out_dir: Path,
    *,
    n_slices: int = 60,
    rows: int = 256,
    cols: int = 256,
) -> List[Path]:
    """Write ``n_slices`` deterministic MONOCHROME2 DICOM files into ``out_dir``.

    Pixel data uses a per-slice fixed seed so the series is byte-identical
    across runs/machines. Slope=1.0, Intercept=-1024.0, IPP increments along
    Z, IOP=identity. Filenames are ``Instance_NNNN.dcm``.
    """
    import numpy as np
    import pydicom
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import ExplicitVRLittleEndian

    out_dir.mkdir(parents=True, exist_ok=True)
    series_uid = "1.2.826.0.1.3680043.8.498.40000000000000000000000000000001"
    study_uid = "1.2.826.0.1.3680043.8.498.50000000000000000000000000000001"

    files: List[Path] = []
    for i in range(n_slices):
        ds = FileDataset(None, {}, preamble=b"\x00" * 128)
        ds.file_meta = Dataset()
        ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
        ds.file_meta.MediaStorageSOPInstanceUID = (
            f"1.2.826.0.1.3680043.8.498.60000000000000000000000000{i:06d}"
        )
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.PatientName = "Synthetic^Overlap"
        ds.PatientID = "SYN001"
        ds.PatientBirthDate = "19800101"
        ds.PatientSex = "M"
        ds.StudyInstanceUID = study_uid
        ds.StudyDate = "20260428"
        ds.StudyTime = "120000"
        ds.AccessionNumber = "SYN001"
        ds.SeriesInstanceUID = series_uid
        ds.SeriesNumber = 999
        ds.Modality = "CT"
        ds.SeriesDescription = "SyntheticOverlap"
        ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
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
        rng = np.random.RandomState(2000 + i)
        px = rng.randint(0, 3000, size=(rows, cols), dtype=np.uint16)
        ds.PixelData = px.tobytes()
        ds.is_implicit_VR = False
        ds.is_little_endian = True
        p = out_dir / f"Instance_{i + 1:04d}.dcm"
        pydicom.dcmwrite(str(p), ds)
        files.append(p)
    return files


# ── Runner ──────────────────────────────────────────────────────────────────

class _OverlapTagFilter(logging.Filter):
    """Allow only records that contain the [OVERLAP_SCENARIO] token."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 — std API
        try:
            return "[OVERLAP_SCENARIO]" in record.getMessage()
        except Exception:
            return False


def _attach_overlap_log_handler(log_path: Path) -> logging.Handler:
    """Attach a FileHandler that captures only [OVERLAP_SCENARIO] INFO lines."""
    handler = logging.FileHandler(str(log_path), mode="w", encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.addFilter(_OverlapTagFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    target = logging.getLogger("modules.viewer.fast.lightweight_2d_pipeline")
    target.setLevel(logging.INFO)
    target.addHandler(handler)
    # Ensure propagation so our handler is reachable even if root has no INFO sink.
    target.propagate = True
    return handler


def _detach_overlap_log_handler(handler: logging.Handler) -> None:
    target = logging.getLogger("modules.viewer.fast.lightweight_2d_pipeline")
    try:
        target.removeHandler(handler)
    finally:
        try:
            handler.close()
        except Exception:
            pass


def run_synthetic_overlap(
    *,
    duration_s: float = 5.0,
    set_slice_hz: int = 30,
    drip_hz: int = 10,  # accepted for API symmetry; series is materialized up-front
    sample_rate: int = 1,
    n_slices: int = 60,
    rows: int = 256,
    cols: int = 256,
    output_path: Optional[Path] = None,
    keep_log: bool = False,
) -> Dict[str, Any]:
    """Drive the FAST pipeline through a stack-drag while heavy_download=True.

    Returns the parsed harness payload (as written to ``output_path`` if
    provided). When ``keep_log`` is True the raw ``.log`` capture file is
    preserved next to the output JSON, otherwise it is deleted.
    """
    # 1-in-N sampling. Default 1 = every overlap return path emits a tag —
    # synthetic runs need predictable counts.
    os.environ["AIPACS_OVERLAP_LOG_SAMPLE"] = str(int(sample_rate))

    # Reload the pipeline module so it picks up the env override defined
    # at module-import time (`_OVERLAP_LOG_SAMPLE_N`).
    import importlib

    try:
        import modules.viewer.fast.lightweight_2d_pipeline as _pipeline_mod
        _pipeline_mod = importlib.reload(_pipeline_mod)
    except Exception:
        import modules.viewer.fast.lightweight_2d_pipeline as _pipeline_mod  # type: ignore
    Lightweight2DPipeline = _pipeline_mod.Lightweight2DPipeline
    PipelineConfig = _pipeline_mod.PipelineConfig

    # Activate the heavy_download gate via ZetaBoost globals.
    from modules.zeta_boost.cache_engine import _zb_globals
    prior_active = bool(getattr(_zb_globals, "_GLOBAL_DOWNLOAD_ACTIVE", False))

    tmp_root = Path(tempfile.mkdtemp(prefix="aipacs_synth_overlap_"))
    series_dir = tmp_root / "series"
    log_path = tmp_root / "overlap.log"
    handler = _attach_overlap_log_handler(log_path)

    started = time.perf_counter()
    metrics: Dict[str, Any]
    try:
        _make_synthetic_overlap_series(series_dir, n_slices=n_slices, rows=rows, cols=cols)

        cfg = PipelineConfig(
            pixel_cache_size=n_slices * 2,
            frame_cache_size=n_slices * 2,
            prefetch_radius=3,
            prefetch_workers=1,
            opencv_filter_enabled=False,
        )
        pipeline = Lightweight2DPipeline(config=cfg)
        pipeline.open_series(str(series_dir))
        # Tag the series so `_maybe_emit_overlap_tag` passes its truthy check.
        pipeline._series_number = "999"

        # Activate the heavy_download gate.
        _zb_globals.set_global_download_active(True)

        # Drag burst.
        pipeline.set_fast_interaction(True, "drag")

        deadline = time.perf_counter() + float(duration_s)
        period = 1.0 / max(1, int(set_slice_hz))
        idx = 0
        direction = 1
        next_tick = time.perf_counter()
        frame_count = 0
        while time.perf_counter() < deadline:
            try:
                pipeline.get_rendered_frame(idx, interaction_type="drag")
            except Exception:
                # Instrumentation must never break the runner.
                pass
            frame_count += 1
            idx += direction
            if idx >= n_slices - 1:
                idx = n_slices - 1
                direction = -1
            elif idx <= 0:
                idx = 0
                direction = 1
            next_tick += period
            sleep_for = next_tick - time.perf_counter()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                # Falling behind — reset cadence to avoid runaway catch-up.
                next_tick = time.perf_counter()

        # Settle and final render.
        pipeline.set_fast_interaction(False)
        try:
            pipeline.get_rendered_frame(idx)
        except Exception:
            pass

        # Flush the file handler.
        try:
            handler.flush()
        except Exception:
            pass

        # Parse the captured log via the harness.
        from tools.performance.clearcanvas_aipacs_kpi_harness import parse_overlap_log_file

        payload = parse_overlap_log_file(log_path)
        elapsed = time.perf_counter() - started
        payload["runner"] = {
            "name": "synthetic_overlap_runner",
            "version": "F0.4",
            "duration_s": round(elapsed, 3),
            "frames_driven": frame_count,
            "set_slice_hz": int(set_slice_hz),
            "drip_hz": int(drip_hz),
            "sample_rate": int(sample_rate),
            "n_slices": int(n_slices),
            "rows": int(rows),
            "cols": int(cols),
        }
        metrics = payload

        if output_path is not None:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            if keep_log:
                kept = output_path.with_suffix(".log")
                try:
                    kept.write_text(log_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
                except Exception:
                    pass

        return metrics
    finally:
        try:
            pipeline.close_series()  # type: ignore[name-defined]
        except Exception:
            pass
        try:
            _zb_globals.set_global_download_active(prior_active)
        except Exception:
            pass
        _detach_overlap_log_handler(handler)
        # Cleanup tmp tree.
        try:
            import shutil
            shutil.rmtree(tmp_root, ignore_errors=True)
        except Exception:
            pass


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="synthetic_overlap_runner",
        description="F0.4 — headless reproducer for the FAST overlap scenario.",
    )
    p.add_argument("--duration", type=float, default=5.0,
                   help="Drag-burst duration in seconds (default: 5.0).")
    p.add_argument("--set-slice-hz", type=int, default=30,
                   help="Synthetic stack-drag rate in Hz (default: 30).")
    p.add_argument("--drip-hz", type=int, default=10,
                   help="Mid-download arrival simulation rate (accepted but no-op in v0).")
    p.add_argument("--sample-rate", type=int, default=1,
                   help="AIPACS_OVERLAP_LOG_SAMPLE value (default: 1 = every frame).")
    p.add_argument("--n-slices", type=int, default=60)
    p.add_argument("--rows", type=int, default=256)
    p.add_argument("--cols", type=int, default=256)
    p.add_argument("--output", type=Path,
                   default=Path("overlap_baseline_v0_synthetic.json"),
                   help="Output JSON path (default: overlap_baseline_v0_synthetic.json).")
    p.add_argument("--keep-log", action="store_true",
                   help="Preserve the captured raw .log next to the JSON output.")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_argparser().parse_args(argv)
    payload = run_synthetic_overlap(
        duration_s=args.duration,
        set_slice_hz=args.set_slice_hz,
        drip_hz=args.drip_hz,
        sample_rate=args.sample_rate,
        n_slices=args.n_slices,
        rows=args.rows,
        cols=args.cols,
        output_path=args.output,
        keep_log=args.keep_log,
    )
    metrics = payload.get("overlap_metrics", {})
    print(f"[F0.4] frames_driven={payload.get('runner', {}).get('frames_driven')} "
          f"sample_count={metrics.get('overlap_sample_count')} "
          f"cache_breakdown={metrics.get('overlap_cache_breakdown')} "
          f"settled_breakdown={metrics.get('overlap_settled_breakdown')}")
    print(f"[F0.4] wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
