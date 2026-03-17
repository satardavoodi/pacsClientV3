"""
Stitch Worker — QThread background worker for N-series chain stitching.

Executes the full multi-series stitching pipeline off the GUI thread:

1. Load all N series as 2-D SimpleITK images.
2. For each adjacent pair, compute a landmark-based transform.
3. Emit per-landmark residuals and **pause** for user confirmation if
   any residual exceeds the accuracy threshold (4 mm).
4. Chain-compose transforms so every series maps into series-0 space.
5. Resample all images into the common (series-0) coordinate space.
6. Build the union canvas.
7. Histogram-match + multi-band blend.
8. Return the stitched ``sitk.Image``.

Author : AI Pacs Team
Created: 2026-02-20  (rewritten for multi-series chain stitching)
"""

from __future__ import annotations

import threading
import traceback
from typing import List, Literal

import numpy as np
import SimpleITK as sitk
from PySide6.QtCore import QThread, Signal

from .landmark_store import LandmarkStore
from .stitch_engine import compute_transform, compute_residuals, load_series_as_2d
from .blend_engine import retouch_and_blend


class StitchWorker(QThread):
    """Background worker that runs the full N-series chain-stitching pipeline.

    When accuracy warnings are detected the worker **pauses** and emits
    ``residuals_report``.  The UI must call ``confirm_continue()`` or
    ``cancel()`` to resume / abort.
    """

    # ------------------------------------------------------------------
    #  Signals
    # ------------------------------------------------------------------
    progress = Signal(str, float)       # (status_text, fraction 0..1)
    completed = Signal(object)          # sitk.Image — stitched result
    error = Signal(str)                 # error message
    # list of dicts: {pair_set, lm_index, label_left, label_right,
    #                 residual_mm, exceeds}
    residuals_report = Signal(list)

    # ------------------------------------------------------------------
    #  Construction
    # ------------------------------------------------------------------
    def __init__(
        self,
        series_dirs: List[str],
        landmark_store: LandmarkStore,
        transform_type: Literal["rigid", "similarity", "affine"] = "affine",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._series_dirs = series_dirs
        self._landmark_store = landmark_store
        self._transform_type = transform_type

        self._cancelled = False
        self._cancel_lock = threading.Lock()

        # Pause / confirmation gate
        self._gate = threading.Event()
        self._gate.set()                  # starts open (no pause)
        self._user_confirmed = True       # default: proceed

    # ------------------------------------------------------------------
    #  Cancel / confirm support
    # ------------------------------------------------------------------
    def cancel(self) -> None:
        with self._cancel_lock:
            self._cancelled = True
        # Unblock the gate so the thread can exit
        self._gate.set()

    def is_cancelled(self) -> bool:
        with self._cancel_lock:
            return self._cancelled

    def confirm_continue(self) -> None:
        """Called from the UI thread to let the worker proceed after a
        residual warning."""
        self._user_confirmed = True
        self._gate.set()

    def reject_continue(self) -> None:
        """Called from the UI thread to tell the worker to abort after a
        residual warning (user chose to re-adjust)."""
        self._user_confirmed = False
        self._gate.set()

    # ------------------------------------------------------------------
    #  Main pipeline
    # ------------------------------------------------------------------
    def run(self) -> None:  # noqa: C901
        try:
            N = len(self._series_dirs)
            if N < 2:
                self.error.emit("Need at least 2 series for stitching")
                return

            # load + transforms + canvas_bounds + resample_each + blend
            total_steps = N + (N - 1) + 1 + N + 1

            # ── Stage 1: Load all series ─────────────────────────────
            images: List[sitk.Image] = []
            for i, d in enumerate(self._series_dirs):
                if self.is_cancelled():
                    return
                self.progress.emit(f"Loading series {i + 1}/{N}…", i / total_steps)
                img = load_series_as_2d(d)
                images.append(img)
                print(f"[StitchWorker] Series {i}: size={img.GetSize()}, "
                      f"spacing={img.GetSpacing()}, origin={img.GetOrigin()}")

            # ── Stage 2: Compute per-pair transforms ─────────────────
            pair_transforms: List[sitk.Transform] = []
            all_residual_entries: list = []
            any_exceeds = False

            for ps in range(N - 1):
                if self.is_cancelled():
                    return
                step = N + ps
                self.progress.emit(
                    f"Computing transform {ps + 1}/{N - 1}…",
                    step / total_steps,
                )
                left_flat = self._landmark_store.get_left_flat(ps)
                right_flat = self._landmark_store.get_right_flat(ps)
                n_pts = len(left_flat) // 2
                print(f"[StitchWorker] Pair {ps}: "
                      f"left_pts={n_pts}, right_pts={len(right_flat)//2}")

                t = compute_transform(left_flat, right_flat, self._transform_type)
                pair_transforms.append(t)
                print(f"[StitchWorker] Transform[{ps}]: {t.GetName()}")

                # ── Per-landmark residuals with labels ───────────────
                resids = compute_residuals(left_flat, right_flat, t)
                for lm_i, r_mm in enumerate(resids):
                    lbl_l, lbl_r = LandmarkStore.pair_label(lm_i)
                    exceeds = r_mm > 4.0
                    if exceeds:
                        any_exceeds = True
                    entry = {
                        "pair_set": ps,
                        "lm_index": lm_i,
                        "label_left": lbl_l,
                        "label_right": lbl_r,
                        "residual_mm": round(r_mm, 3),
                        "exceeds": exceeds,
                    }
                    all_residual_entries.append(entry)
                    status = "⚠ EXCEEDS 4 mm" if exceeds else "OK"
                    print(f"[StitchWorker]   {lbl_l}–{lbl_r}: "
                          f"{r_mm:.3f} mm  [{status}]")

            # ── Emit residual report ─────────────────────────────────
            self.residuals_report.emit(all_residual_entries)

            # If any landmark exceeds threshold → pause and wait for
            # user confirmation before doing the expensive stages.
            if any_exceeds:
                self.progress.emit("Waiting for accuracy confirmation…", 0.35)
                self._gate.clear()        # block
                self._gate.wait()         # sleep until UI calls confirm/reject
                if self.is_cancelled() or not self._user_confirmed:
                    self.progress.emit("Aborted by user", 0.0)
                    self.error.emit(
                        "Stitching aborted — please re-adjust landmarks "
                        "and try again."
                    )
                    return

            # ── Stage 3: Build composite transforms ──────────────────
            composites: List[sitk.Transform] = [
                sitk.Transform(2, sitk.sitkIdentity)
            ]
            for k in range(1, N):
                if k == 1:
                    composites.append(pair_transforms[0])
                else:
                    ct = sitk.CompositeTransform(2)
                    for i in range(k - 1, -1, -1):
                        ct.AddTransform(pair_transforms[i])
                    composites.append(ct)

            # ── Stage 4: Compute union canvas ────────────────────────
            if self.is_cancelled():
                return
            step = N + (N - 1)
            self.progress.emit("Computing canvas bounds…", step / total_steps)

            all_corners: List[tuple] = []
            for k in range(N):
                img_k = images[k]
                sz = img_k.GetSize()
                corners_img = [
                    img_k.TransformIndexToPhysicalPoint((0, 0)),
                    img_k.TransformIndexToPhysicalPoint((sz[0] - 1, 0)),
                    img_k.TransformIndexToPhysicalPoint((0, sz[1] - 1)),
                    img_k.TransformIndexToPhysicalPoint((sz[0] - 1, sz[1] - 1)),
                ]
                if k == 0:
                    all_corners.extend(corners_img)
                else:
                    try:
                        inv_ct = sitk.CompositeTransform(2)
                        for i in range(k):
                            inv_pair = pair_transforms[i].GetInverse()
                            inv_ct.AddTransform(inv_pair)
                        for c in corners_img:
                            cp = inv_ct.TransformPoint(c)
                            all_corners.append(cp)
                    except Exception as exc:
                        print(f"[StitchWorker] Cannot invert transform for "
                              f"series {k}: {exc}  — using landmark estimate")
                        lf = self._landmark_store.get_left_flat(k - 1)
                        rf = self._landmark_store.get_right_flat(k - 1)
                        if lf and rf:
                            np_ = len(lf) // 2
                            dx = sum(lf[j*2]   - rf[j*2]   for j in range(np_)) / np_
                            dy = sum(lf[j*2+1] - rf[j*2+1] for j in range(np_)) / np_
                            for c in corners_img:
                                all_corners.append((c[0] + dx, c[1] + dy))
                        else:
                            all_corners.extend(corners_img)

            xs = [pt[0] for pt in all_corners]
            ys = [pt[1] for pt in all_corners]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)

            finest_sx = min(im.GetSpacing()[0] for im in images)
            finest_sy = min(im.GetSpacing()[1] for im in images)

            nx = int(np.ceil((max_x - min_x) / finest_sx)) + 1
            ny = int(np.ceil((max_y - min_y) / finest_sy)) + 1

            canvas = sitk.Image((nx, ny), sitk.sitkFloat32)
            canvas.SetOrigin((min_x, min_y))
            canvas.SetSpacing((finest_sx, finest_sy))
            canvas.SetDirection((1.0, 0.0, 0.0, 1.0))

            print(f"[StitchWorker] Canvas: size=({nx},{ny}), "
                  f"origin=({min_x:.2f},{min_y:.2f}), "
                  f"spacing=({finest_sx:.4f},{finest_sy:.4f})")

            # ── Stage 5: Resample each image onto the union canvas ───
            arrays: List[np.ndarray] = []
            for k in range(N):
                if self.is_cancelled():
                    return
                step_k = N + (N - 1) + 1 + k
                self.progress.emit(
                    f"Resampling series {k + 1}/{N}…", step_k / total_steps
                )
                resampled = sitk.Resample(
                    images[k],
                    canvas,
                    composites[k],
                    sitk.sitkLinear,
                    0.0,
                    sitk.sitkFloat32,
                )
                arr = sitk.GetArrayFromImage(resampled).astype(np.float64)
                arrays.append(arr)
                nonzero = int((arr != 0).sum())
                print(f"[StitchWorker] Resampled series {k}: "
                      f"shape={arr.shape}, nonzero_pixels={nonzero}")

            del images

            # ── Stage 6: Histogram match + multi-band blend ─────────
            if self.is_cancelled():
                return
            step = N + (N - 1) + 1 + N
            self.progress.emit("Retouching seams & blending…", step / total_steps)
            blended = retouch_and_blend(arrays)
            del arrays

            # ── Wrap result as sitk.Image ────────────────────────────
            if self.is_cancelled():
                return
            self.progress.emit("Finalising stitched image…", 0.98)
            stitched = sitk.GetImageFromArray(blended.astype(np.float32))
            stitched.SetOrigin(canvas.GetOrigin())
            stitched.SetSpacing(canvas.GetSpacing())
            stitched.SetDirection(canvas.GetDirection())
            del blended, canvas

            self.progress.emit("Stitching complete", 1.0)
            print("[StitchWorker] Pipeline finished successfully")
            self.completed.emit(stitched)

        except Exception as exc:
            tb = traceback.format_exc()
            print(f"[StitchWorker] ERROR: {exc}\n{tb}")
            self.error.emit(str(exc))
