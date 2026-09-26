"""Render a synthetic Y-invariant phantom while scrolling the coronal camera.

Only numeric error summaries are emitted; no clinical images are used.
Run in a separate process with the repository interpreter.
Quote floating-point CLI arguments in PowerShell: unquoted numeric arguments
can lose significant digits before Python receives them. This probe intentionally
detects numerical sensitivity. Exit 1 means rendered stationarity failed.
The alternative sampling switches affect this standalone probe only.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import vtkmodules.all as vtk
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from modules.mpr.zeta_mpr.mpr_viewer._mpr_crosshair_interact import stable_scroll_camera_step


def run(depth, origin, spacing, size, zoom, screen_sampling=False, optimize=True, frames=41,
        configure=None):
    x = np.arange(512)[None, :]
    z = np.arange(depth)[:, None]
    phantom = (200 + 600 * ((x // 13 + z // 17) % 2)).astype(np.int16)
    pixels = np.broadcast_to(phantom[:, None, :], (depth, 512, 512)).copy()
    volume = vtk.vtkImageData()
    volume.SetDimensions(512, 512, depth)
    volume.SetOrigin(origin)
    volume.SetSpacing(spacing)
    scalars = numpy_to_vtk(pixels.ravel(), deep=False)
    volume.GetPointData().SetScalars(scalars)
    mapper = vtk.vtkImageResliceMapper()
    mapper.SetInputData(volume)
    mapper.SliceFacesCameraOn()
    mapper.SliceAtFocalPointOn()
    mapper.SetResampleToScreenPixels(screen_sampling)
    mapper.AutoAdjustImageQualityOff()
    mapper.GetImageReslice().SetOptimization(optimize)
    actor = vtk.vtkImageSlice()
    actor.SetMapper(mapper)
    actor.GetProperty().SetInterpolationTypeToLinear()
    actor.GetProperty().SetColorWindow(1000)
    actor.GetProperty().SetColorLevel(500)
    if configure is not None:
        configure(actor, mapper)
    renderer = vtk.vtkRenderer()
    renderer.AddViewProp(actor)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(*size)
    window.AddRenderer(renderer)
    camera = renderer.GetActiveCamera()
    center = volume.GetCenter()
    camera.SetFocalPoint(center)
    camera.SetPosition(center[0], center[1] - 1, center[2])
    camera.SetViewUp(0, 0, -1)
    camera.ParallelProjectionOn()
    renderer.ResetCamera()
    camera.Zoom(zoom)
    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.ReadFrontBufferOff()
    capture.ShouldRerenderOff()
    baseline = None
    changes = []
    amplitudes = []
    grids = []
    resliced_baseline = None
    resliced_changes = []
    resliced_amplitudes = []
    first_jump_alignment = None
    render_ms = []
    try:
        for index in range(frames):
            if index:
                focal, position = stable_scroll_camera_step(
                    camera.GetFocalPoint(), camera.GetPosition(), (0, 1, 0), spacing[1])
                camera.SetFocalPoint(focal)
                camera.SetPosition(position)
            started = time.perf_counter()
            window.Render()
            render_ms.append((time.perf_counter() - started) * 1000)
            output = mapper.GetImageReslice().GetOutput()
            resliced = vtk_to_numpy(output.GetPointData().GetScalars()).copy()
            if resliced_baseline is None:
                resliced_baseline = resliced
            resliced_changes.append(int(np.count_nonzero(resliced != resliced_baseline)))
            resliced_amplitudes.append(int(np.max(np.abs(
                resliced.astype(np.int32) - resliced_baseline.astype(np.int32)))))
            if first_jump_alignment is None and resliced_amplitudes[-1] > 10:
                width, height, _ = output.GetDimensions()
                reference = resliced_baseline.reshape(height, width).astype(np.int32)
                current = resliced.reshape(height, width).astype(np.int32)
                errors = []
                for shift in (-1, 0, 1):
                    shifted = np.roll(current, shift, axis=0)
                    errors.append(float(np.mean(np.abs(shifted[2:-2, 2:-2] -
                                                       reference[2:-2, 2:-2]))))
                first_jump_alignment = {"row_shifts": [-1, 0, 1], "mean_errors": errors}
            grids.append({"origin": output.GetOrigin(), "spacing": output.GetSpacing(),
                          "extent": output.GetExtent()})
            capture.Modified()
            capture.Update()
            frame = vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars()).copy()
            if baseline is None:
                baseline = frame
            changes.append(int(np.count_nonzero(np.any(frame != baseline, axis=1))))
            amplitudes.append(int(np.max(np.abs(frame.astype(np.int16) - baseline))))
    finally:
        actor.ReleaseGraphicsResources(window)
        window.Finalize()
    return {"depth": depth, "window_size": size, "zoom": zoom,
            "frames": len(changes), "changed_pixels_max": max(changes),
            "max_channel_difference": max(amplitudes),
            "screen_sampling": screen_sampling,
            "optimization": optimize,
            "warm_render_median_ms": float(np.median(render_ms[1:])),
            "grids_first_three": grids[:3],
            "resliced_changes_first_three": resliced_changes[:3],
            "resliced_max_difference": max(resliced_amplitudes),
            "first_jump_alignment": first_jump_alignment,
            "changed_pixels_by_frame": changes}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--depth", type=int, default=372)
    parser.add_argument("--origin", type=float, nargs=3, default=(-200, -203, -198))
    parser.add_argument("--spacing", type=float, nargs=3, default=(.7949453, .7949453, 1.25))
    parser.add_argument("--size", type=int, nargs=2, default=(600, 500))
    parser.add_argument("--zoom", type=float, default=1.2)
    parser.add_argument("--screen-sampling", action="store_true")
    parser.add_argument("--no-optimization", action="store_true")
    parser.add_argument("--frames", type=int, default=41)
    args = parser.parse_args()
    result = run(args.depth, args.origin, args.spacing, args.size, args.zoom,
                 args.screen_sampling, not args.no_optimization, args.frames)
    print(json.dumps(result))
    sys.exit(1 if result["changed_pixels_max"] else 0)
