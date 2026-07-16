"""
Factor 3 of the cross-view heatmap — histogram / regional appearance similarity.

The source lesion box has a local intensity signature: microcalcifications skew
DENSE (bright), a lipoma skews FATTY (dark), a mass may be hyper- or iso-dense.
The corresponding lesion in the other view should carry a *similar* signature. So
we compare the source box's intensity histogram against candidate regions inside
the predicted area in the target view, and turn the comparison into a [0, 1] score.

This is a PIXEL-level module (numpy), unlike the pure geometry core — but it is
still headless-testable (numpy only; no Qt/VTK/pydicom). The caller supplies the
already-decoded pixel arrays; this module never reads DICOM itself.

Design notes:
  * Compare over a SHARED intensity range (the source region's robust 1st–99th
    percentile) so "how dense is this region" is measured on the same axis in both
    views — that is what makes a dense source match a dense target and reject a
    fatty one.
  * Two sub-signals, combined: DISTRIBUTION shape (histogram intersection) and
    DENSITY level (mean-intensity agreement). Shape catches texture/heterogeneity;
    density catches the hyper/iso/hypo axis the radiologist described.
  * Everything is robust to degenerate inputs (empty box, flat region, NaNs) and
    returns a neutral 0.5 rather than raising — a plumbing failure must never count
    as evidence for or against a candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy is present in the app + test env
    np = None


_DEFAULT_BINS = 32
_NEUTRAL = 0.5


@dataclass
class AppearanceFeatures:
    """The source region's intensity signature, computed once and reused."""
    histogram: "np.ndarray"          # normalised (sums to 1) over `bin_edges`
    bin_edges: "np.ndarray"
    mean: float
    std: float
    value_lo: float                  # shared-range lower bound (p1)
    value_hi: float                  # shared-range upper bound (p99)
    ok: bool = True


def _crop(pixels, box_px: Sequence[float]):
    """Return the pixel sub-array for [x1,y1,x2,y2], clamped to the image. None if empty."""
    if np is None or pixels is None:
        return None
    try:
        h, w = pixels.shape[:2]
        x1, y1, x2, y2 = [float(v) for v in box_px]
        xlo, xhi = sorted((x1, x2))
        ylo, yhi = sorted((y1, y2))
        xlo = max(0, int(round(xlo))); xhi = min(w, int(round(xhi)))
        ylo = max(0, int(round(ylo))); yhi = min(h, int(round(yhi)))
        if xhi - xlo < 2 or yhi - ylo < 2:
            return None
        sub = pixels[ylo:yhi, xlo:xhi]
        return sub if sub.size else None
    except Exception:
        return None


def source_features(
    pixels,
    box_px: Sequence[float],
    *,
    bins: int = _DEFAULT_BINS,
) -> AppearanceFeatures:
    """
    Compute the source lesion box's appearance signature.

    The shared intensity range is the region's 1st–99th percentile (robust to a
    few extreme pixels). Both the source and every candidate histogram are then
    built over THIS range so they are directly comparable.
    """
    sub = _crop(pixels, box_px)
    if sub is None:
        return AppearanceFeatures(None, None, 0.0, 0.0, 0.0, 1.0, ok=False)
    try:
        vals = sub.astype("float64").ravel()
        lo = float(np.percentile(vals, 1.0))
        hi = float(np.percentile(vals, 99.0))
        if not (hi > lo):
            hi = lo + 1.0
        hist, edges = np.histogram(vals, bins=bins, range=(lo, hi))
        total = hist.sum()
        hist = (hist / total) if total > 0 else hist.astype("float64")
        return AppearanceFeatures(
            histogram=hist, bin_edges=edges,
            mean=float(vals.mean()), std=float(vals.std()),
            value_lo=lo, value_hi=hi, ok=True,
        )
    except Exception:
        return AppearanceFeatures(None, None, 0.0, 0.0, 0.0, 1.0, ok=False)


def _hist_over_range(sub, lo: float, hi: float, bins: int):
    vals = sub.astype("float64").ravel()
    hist, _ = np.histogram(vals, bins=bins, range=(lo, hi))
    total = hist.sum()
    return (hist / total) if total > 0 else hist.astype("float64"), float(vals.mean())


def _similarity(src: AppearanceFeatures, cand_hist, cand_mean: float) -> float:
    """Combine histogram-intersection (shape) and mean agreement (density)."""
    # Shape: histogram intersection in [0,1] (1 = identical distribution).
    shape = float(np.minimum(src.histogram, cand_hist).sum())
    # Density: how close the mean intensity is, scaled by the shared range.
    span = max(src.value_hi - src.value_lo, 1e-6)
    density = float(np.exp(-abs(cand_mean - src.mean) / span))
    return max(0.0, min(1.0, 0.6 * shape + 0.4 * density))


def candidate_appearance_score(
    src: AppearanceFeatures,
    target_pixels,
    candidate_box_px: Sequence[float],
    *,
    bins: int = _DEFAULT_BINS,
) -> float:
    """
    Appearance similarity in [0, 1] between the source signature and a candidate
    box in the target view. Neutral 0.5 when it can't be computed (never raises).
    """
    if np is None or src is None or not src.ok or target_pixels is None:
        return _NEUTRAL
    sub = _crop(target_pixels, candidate_box_px)
    if sub is None:
        return _NEUTRAL
    try:
        cand_hist, cand_mean = _hist_over_range(sub, src.value_lo, src.value_hi, bins)
        return _similarity(src, cand_hist, cand_mean)
    except Exception:
        return _NEUTRAL


def build_appearance_map(
    src: AppearanceFeatures,
    target_pixels,
    box_size_px: Tuple[float, float],
    bbox_px: Tuple[int, int, int, int],
    *,
    step_px: int = 24,
    bins: int = _DEFAULT_BINS,
) -> Optional[Tuple["np.ndarray", Tuple[int, int, int, int], int]]:
    """
    Sliding-window appearance-similarity map over the region's bounding box
    (`bbox_px` = x1,y1,x2,y2). Returns (map2d, bbox, step) or None.

    Restricted to the predicted region's bbox (never the whole image) so the cost
    stays bounded; the window is the source lesion's physical size. Used for the
    dense visual heatmap; per-candidate scoring uses `candidate_appearance_score`.
    """
    if np is None or src is None or not src.ok or target_pixels is None:
        return None
    try:
        H, W = target_pixels.shape[:2]
        x1, y1, x2, y2 = bbox_px
        x1 = max(0, int(x1)); y1 = max(0, int(y1))
        x2 = min(W, int(x2)); y2 = min(H, int(y2))
        bw = max(8, int(round(box_size_px[0])))
        bh = max(8, int(round(box_size_px[1])))
        if x2 - x1 < 4 or y2 - y1 < 4:
            return None
        ys = list(range(y1, y2, max(1, step_px)))
        xs = list(range(x1, x2, max(1, step_px)))
        out = np.full((len(ys), len(xs)), _NEUTRAL, dtype="float32")
        for iy, cy in enumerate(ys):
            for ix, cx in enumerate(xs):
                box = (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)
                sub = _crop(target_pixels, box)
                if sub is None:
                    continue
                ch, cm = _hist_over_range(sub, src.value_lo, src.value_hi, bins)
                out[iy, ix] = _similarity(src, ch, cm)
        return out, (x1, y1, x2, y2), max(1, step_px)
    except Exception:
        return None


# ─── Serialisable pattern descriptor (the lesion-box "matrix" features) ───────
#
# `source_features` above is the SCORING signature (histogram + mean) used on the
# hot path. `describe_region` below is the STORAGE descriptor: the fuller set of
# pattern features the box matrix contains — first-order stats, rotation-averaged
# GLCM/Haralick texture, and the microcalcification constellation ("4 bright dots
# → 4 bright dots"). It is computed ONCE per lesion at persist time and written to
# the lesion feature store; it never touches the scoring path, so scoring stays
# byte-identical. Pure numpy, never raises, returns a plain JSON-able dict.

_GLCM_LEVELS = 16
_DESC_MAX_DIM = 384          # cap the analysed window so cost stays bounded
_MICROCALC_K = 2.5           # bright-blob threshold = mean + k·std of the high-pass
_MICROCALC_MAX_ON = 6000     # if more pixels than this fire, it is not a MC cluster


def _center_window(sub, max_dim: int):
    """Centre-crop `sub` to at most max_dim on each side (bounds texture/blob cost)."""
    h, w = sub.shape[:2]
    if h <= max_dim and w <= max_dim:
        return sub
    y0 = max(0, (h - max_dim) // 2)
    x0 = max(0, (w - max_dim) // 2)
    return sub[y0:y0 + max_dim, x0:x0 + max_dim]


def _first_order(vals) -> dict:
    """mean/std/skew/excess-kurtosis/entropy/percentiles/high-density fraction."""
    mean = float(vals.mean())
    std = float(vals.std())
    lo = float(np.percentile(vals, 1.0))
    hi = float(np.percentile(vals, 99.0))
    if std > 1e-9:
        z = (vals - mean) / std
        skew = float((z ** 3).mean())
        kurt = float((z ** 4).mean() - 3.0)
    else:
        skew = 0.0
        kurt = 0.0
    # Shannon entropy over a 64-bin histogram of the robust range.
    rng = (lo, hi) if hi > lo else (lo, lo + 1.0)
    hist, _ = np.histogram(vals, bins=64, range=rng)
    p = hist.astype("float64")
    s = p.sum()
    if s > 0:
        p = p / s
        nz = p[p > 0]
        entropy = float(-(nz * np.log2(nz)).sum())
    else:
        entropy = 0.0
    # "bright fraction" — a microcalcification-sensitive measure.
    hi_frac = float((vals > (mean + 2.0 * std)).mean()) if std > 1e-9 else 0.0
    return {
        "mean": round(mean, 3), "std": round(std, 3),
        "skew": round(skew, 4), "kurtosis": round(kurt, 4),
        "entropy": round(entropy, 4),
        "p1": round(lo, 3), "p99": round(hi, 3),
        "high_density_fraction": round(hi_frac, 5),
    }


def _glcm_haralick(sub, levels: int = _GLCM_LEVELS) -> Optional[dict]:
    """
    Rotation-AVERAGED Haralick features over 4 offsets (0°, 45°, 90°, 135°).

    Rotation-averaging is deliberate: it makes the texture descriptor orientation-
    independent, which is what lets it survive the CC↔MLO view rotation. Returns
    None on a degenerate region.
    """
    try:
        v = sub.astype("float64")
        lo = float(np.percentile(v, 1.0))
        hi = float(np.percentile(v, 99.0))
        if not (hi > lo):
            # Robust range collapsed (e.g. a few bright microcalcs on a flat field,
            # where p99 is still background). Fall back to full min–max so texture is
            # still captured; only a truly constant region yields None.
            lo = float(v.min())
            hi = float(v.max())
            if not (hi > lo):
                return None
        q = np.clip(((v - lo) / (hi - lo) * (levels - 1)).round().astype("int64"), 0, levels - 1)
        offsets = ((0, 1), (1, 0), (1, 1), (1, -1))
        acc = {"contrast": 0.0, "homogeneity": 0.0, "asm": 0.0, "correlation": 0.0, "entropy": 0.0}
        used = 0
        idx = np.arange(levels, dtype="float64")
        for dy, dx in offsets:
            a = q[max(0, dy):q.shape[0] + min(0, dy), max(0, dx):q.shape[1] + min(0, dx)]
            b = q[max(0, -dy):q.shape[0] + min(0, -dy), max(0, -dx):q.shape[1] + min(0, -dx)]
            if a.size == 0:
                continue
            glcm = np.zeros((levels, levels), dtype="float64")
            np.add.at(glcm, (a.ravel(), b.ravel()), 1.0)
            glcm = glcm + glcm.T                     # symmetric
            tot = glcm.sum()
            if tot <= 0:
                continue
            P = glcm / tot
            I, J = np.meshgrid(idx, idx, indexing="ij")
            acc["contrast"] += float((P * (I - J) ** 2).sum())
            acc["homogeneity"] += float((P / (1.0 + (I - J) ** 2)).sum())
            acc["asm"] += float((P * P).sum())
            nz = P[P > 0]
            acc["entropy"] += float(-(nz * np.log2(nz)).sum())
            mu_i = float((I * P).sum()); mu_j = float((J * P).sum())
            si = float(((I - mu_i) ** 2 * P).sum()) ** 0.5
            sj = float(((J - mu_j) ** 2 * P).sum()) ** 0.5
            if si > 1e-9 and sj > 1e-9:
                acc["correlation"] += float(((I - mu_i) * (J - mu_j) * P).sum() / (si * sj))
            used += 1
        if used == 0:
            return None
        return {k: round(val / used, 5) for k, val in acc.items()}
    except Exception:
        return None


def _box_blur(a, radius: int):
    """Mean filter (window 2r+1) via an integral image. Pure numpy, edge-safe."""
    H, W = a.shape
    ii = np.zeros((H + 1, W + 1), dtype="float64")
    ii[1:, 1:] = np.cumsum(np.cumsum(a.astype("float64"), axis=0), axis=1)
    out = np.empty((H, W), dtype="float64")
    for y in range(H):
        y0 = max(0, y - radius); y1 = min(H, y + radius + 1)
        for x in range(W):
            x0 = max(0, x - radius); x1 = min(W, x + radius + 1)
            total = ii[y1, x1] - ii[y0, x1] - ii[y1, x0] + ii[y0, x0]
            out[y, x] = total / ((y1 - y0) * (x1 - x0))
    return out


def _connected_blobs(mask) -> list:
    """
    4-connected components of a boolean mask → list of (area, cy, cx). Iterative
    flood fill (no scipy). Bounded by the caller capping the number of ON pixels.
    """
    H, W = mask.shape
    seen = np.zeros((H, W), dtype=bool)
    blobs = []
    on = np.argwhere(mask)
    for sy, sx in on:
        if seen[sy, sx]:
            continue
        stack = [(sy, sx)]
        seen[sy, sx] = True
        pts = []
        while stack:
            y, x = stack.pop()
            pts.append((y, x))
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        ys = [p[0] for p in pts]; xs = [p[1] for p in pts]
        blobs.append((len(pts), sum(ys) / len(pts), sum(xs) / len(pts)))
    return blobs


def _microcalc_constellation(sub, spacing_mm: Optional[Tuple[float, float]]) -> dict:
    """
    Detect bright, small, high-frequency blobs (candidate microcalcifications) and
    summarise them as a constellation: count, mean size, mean nearest-neighbour
    spacing. This is the view-STABLE cross-view/contralateral fingerprint the
    radiologist described — "if four bright dots here, expect four bright dots
    there". Never raises; `detected=False` on any degeneracy.
    """
    empty = {"detected": False, "count": 0, "mean_area_px": None,
             "mean_area_mm2": None, "mean_nn_spacing_mm": None}
    try:
        v = sub.astype("float64")
        # High-pass: local detail = pixel − local background (box mean, ~1.5 mm).
        radius = 6
        bg = _box_blur(v, radius)
        hp = v - bg
        mu = float(hp.mean()); sd = float(hp.std())
        if sd <= 1e-9:
            return empty
        mask = (hp > (mu + _MICROCALC_K * sd)) & (v > float(v.mean()))
        on = int(mask.sum())
        if on == 0 or on > _MICROCALC_MAX_ON:
            return empty
        blobs = _connected_blobs(mask)
        # Keep compact blobs (microcalcs are small); drop 1-px noise and big areas.
        kept = [b for b in blobs if 2 <= b[0] <= 400]
        if not kept:
            return empty
        sx = float(spacing_mm[0]) if spacing_mm else None
        sy = float(spacing_mm[1]) if spacing_mm else None
        mean_area_px = sum(b[0] for b in kept) / len(kept)
        mean_area_mm2 = (mean_area_px * sx * sy) if (sx and sy) else None
        # Mean nearest-neighbour centroid spacing (cluster tightness).
        nn_mm = None
        if len(kept) >= 2 and sx and sy:
            cents = [(b[1] * sy, b[2] * sx) for b in kept]  # (y_mm, x_mm)
            dists = []
            for i in range(len(cents)):
                best = None
                for j in range(len(cents)):
                    if i == j:
                        continue
                    d = ((cents[i][0] - cents[j][0]) ** 2 + (cents[i][1] - cents[j][1]) ** 2) ** 0.5
                    best = d if best is None else min(best, d)
                if best is not None:
                    dists.append(best)
            if dists:
                nn_mm = sum(dists) / len(dists)
        return {
            "detected": True,
            "count": len(kept),
            "mean_area_px": round(mean_area_px, 2),
            "mean_area_mm2": round(mean_area_mm2, 5) if mean_area_mm2 is not None else None,
            "mean_nn_spacing_mm": round(nn_mm, 3) if nn_mm is not None else None,
        }
    except Exception:
        return empty


def _lesion_type_signature(first_order: dict, mc: dict) -> str:
    """
    A COARSE, explicitly NON-DIAGNOSTIC pattern tag from the descriptor, used only
    to keep like-matched-to-like during correspondence. Never shown as a diagnosis.

      microcalc_like  — several small bright high-frequency blobs
      dense_mass_like — high bright-fraction but few/no discrete blobs
      indeterminate   — neither signature dominates
    """
    if mc.get("detected") and mc.get("count", 0) >= 3:
        return "microcalc_like"
    if first_order.get("high_density_fraction", 0.0) >= 0.05:
        return "dense_mass_like"
    return "indeterminate"


def describe_region(
    pixels,
    box_px: Sequence[float],
    *,
    spacing_mm: Optional[Tuple[float, float]] = None,
) -> dict:
    """
    Full serialisable pattern descriptor for one lesion box — the "matrix features"
    to preserve for future CC↔MLO and R↔L comparisons.

    Returns a JSON-able dict with `ok`. On any failure returns `{"ok": False}` —
    a descriptor is never allowed to raise into the persist/clinical path.
    """
    if np is None or pixels is None:
        return {"ok": False, "reason": "no-pixels"}
    sub = _crop(pixels, box_px)
    if sub is None:
        return {"ok": False, "reason": "empty-box"}
    try:
        if sub.ndim > 2:
            sub = sub[..., 0]
        win = _center_window(sub, _DESC_MAX_DIM)
        vals = win.astype("float64").ravel()
        fo = _first_order(vals)
        glcm = _glcm_haralick(win)
        mc = _microcalc_constellation(win, spacing_mm)
        return {
            "ok": True,
            "n_pixels": int(win.size),
            "density_mean": fo["mean"],
            "first_order": fo,
            "glcm": glcm,
            "microcalc": mc,
            "lesion_type": _lesion_type_signature(fo, mc),
            "descriptor_version": 1,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"error:{exc!r}"}
