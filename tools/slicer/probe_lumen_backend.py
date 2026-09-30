"""Synthetic native VMTK probe, run with the custom runtime's Python launcher."""
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "modules/mpr/advanced_3d_slicer/slicer_modules"))
import numpy as np
import vtk
from aipacs_lumen.backend import analyze, load_vmtk
from aipacs_lumen.process import run_isolated


def main():
    started = time.monotonic()
    from vtkSegmentationCorePython import (vtkSegmentation, vtkSegmentationConverterFactory,
                                          vtkBinaryLabelmapToClosedSurfaceConversionRule)
    vtkSegmentationConverterFactory.GetInstance().RegisterConverterRule(
        vtkBinaryLabelmapToClosedSurfaceConversionRule())
    from aipacs_lumen.seed_presets import ensure_seed_segments, lumen_segment_id
    for mode in ("vascular", "bronchoscopy"):
        segmentation = vtkSegmentation()
        classes, created = ensure_seed_segments(segmentation, mode)
        assert len(classes) == 4 and len(created) == 4
        segmentation.GetSegment(classes["lumen"]).SetName("Renamed target")
        assert ensure_seed_segments(segmentation, mode) == (classes, set())
        assert lumen_segment_id(segmentation, mode) == classes["lumen"]
    z, y, x = np.indices((48, 32, 32))
    mask = (((x - 16) ** 2 + (y - 16) ** 2 <= 36) & (z >= 2) & (z <= 45)).astype(np.uint8)
    affine = np.diag([0.8, 0.8, 1.2, 1.0])
    affine[:3, 3] = [12, -8, 21]
    points = np.array([[16, 16, 3, 1], [16, 16, 44, 1]]) @ affine.T
    result = run_isolated(sys.executable, mask, affine, points[:, :3], None, threading.Event())
    finite = result["area"][np.isfinite(result["area"])]
    assert len(result["points"]) > 30
    assert len(finite) > 0.8 * len(result["points"])
    assert abs(np.median(finite) - np.pi * (6 * .8) ** 2) < 8
    assert 45 < result["distance"][-1] < 60
    output = {"passed": True, "seed_presets_passed": True, "vtk": vtk.vtkVersion.GetVTKVersion(),
              "native_class": load_vmtk().vtkvmtkPolyDataCenterlines().GetClassName(),
              "points": len(result["points"]), "length_mm": float(result["distance"][-1]),
              "median_area_mm2": float(np.median(finite)), "seconds": time.monotonic() - started}
    destination = ROOT / "generated-files/lumen-vmtk/native-probe.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output))


if __name__ == "__main__":
    main()
