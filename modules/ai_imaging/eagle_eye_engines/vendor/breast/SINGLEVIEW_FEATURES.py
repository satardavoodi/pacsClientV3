# Imported inference implementation; provenance in ../provenance.json.
import os, math, json, warnings, sys
from typing import Tuple, Optional, Dict
import numpy as np
import pandas as pd
import itk
from scipy import ndimage as ndi
from scipy.spatial import ConvexHull
INPUT_CSV = ''
OUTPUT_CSV = ''
VERBOSE = True
warnings.filterwarnings('ignore', category=UserWarning)

class _Tee:

    def __init__(self, log_fp, *streams):
        self.log_fp = log_fp
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
                s.flush()
            except Exception:
                pass
        try:
            self.log_fp.write(data)
            self.log_fp.flush()
        except Exception:
            pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass
        try:
            self.log_fp.flush()
        except Exception:
            pass

def set_input_csv(path: str):
    global INPUT_CSV
    INPUT_CSV = str(path)

def set_output_csv(path: str):
    global OUTPUT_CSV
    OUTPUT_CSV = str(path)

def set_verbose(flag: bool=True):
    global VERBOSE
    VERBOSE = bool(flag)

def get_stage2_outputs() -> Dict[str, str]:
    return {'output_csv': OUTPUT_CSV}

def _log(m: str):
    if VERBOSE:
        print(m)

def _load_meta(path: str) -> dict:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _load_roi_from_row(row: pd.Series) -> Tuple[Optional[np.ndarray], dict, str]:
    meta = {}
    npy_path = str(row.get('lesion_npy', '')).strip()
    if npy_path and os.path.isfile(npy_path):
        try:
            roi = np.load(npy_path).astype(np.float32, copy=False)
            meta_path = str(row.get('lesion_meta', '')).strip()
            if meta_path and os.path.isfile(meta_path):
                meta = _load_meta(meta_path)
            return (roi, meta, '')
        except Exception as e:
            return (None, {}, f'load_npy_failed: {e}')
    png_path = str(row.get('lesion_image', '')).strip()
    if png_path and os.path.isfile(png_path):
        try:
            im = itk.imread(png_path)
            arr = itk.GetArrayFromImage(im)
            if arr.ndim == 3:
                arr = arr[0]
            arr = arr.astype(np.float32, copy=False)
            meta_path = str(row.get('lesion_meta', '')).strip()
            if meta_path and os.path.isfile(meta_path):
                meta = _load_meta(meta_path)
                vmin = float(meta.get('png_u16_linear_min', np.nan))
                vmax = float(meta.get('png_u16_linear_max', np.nan))
                if np.isfinite(vmin) and np.isfinite(vmax) and (vmax > vmin):
                    roi = arr / 65535.0 * (vmax - vmin) + vmin
                    roi = roi.astype(np.float32, copy=False)
                else:
                    a_min, a_max = (float(np.nanmin(arr)), float(np.nanmax(arr)))
                    roi = arr if a_max <= a_min else (arr - a_min) / (a_max - a_min)
            else:
                a_min, a_max = (float(np.nanmin(arr)), float(np.nanmax(arr)))
                roi = arr if a_max <= a_min else (arr - a_min) / (a_max - a_min)
            return (roi.astype(np.float32, copy=False), meta, '')
        except Exception as e:
            return (None, {}, f'load_png_failed: {e}')
    return (None, {}, 'no_roi_found')

def _pixel_spacing_mm(meta: dict) -> Tuple[float, float]:
    r = float(meta.get('pixel_spacing_row_mm', np.nan))
    c = float(meta.get('pixel_spacing_col_mm', np.nan))
    return (r, c)

def segment_lesion_mask(g: np.ndarray) -> np.ndarray:
    H, W = g.shape
    try:
        im = itk.image_view_from_array(g.astype(np.float32, copy=False))
        otsu = itk.OtsuThresholdImageFilter.New(im)
        otsu.SetInsideValue(0)
        otsu.SetOutsideValue(1)
        otsu.Update()
        m = itk.GetArrayFromImage(otsu.GetOutput()).astype(bool)
        lbl, n = ndi.label(m)
        if n <= 0:
            raise ValueError('no components')
        sizes = ndi.sum(np.ones_like(lbl), lbl, index=range(1, n + 1))
        keep_label = int(np.argmax(sizes) + 1)
        m = lbl == keep_label
        m = ndi.binary_fill_holes(m)
        m = ndi.binary_closing(m, structure=_disk(2))
        return m.astype(bool)
    except Exception:
        return np.ones_like(g, dtype=bool)

def _disk(r: int) -> np.ndarray:
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r

def boundary_band(mask: np.ndarray, width: int=2) -> np.ndarray:
    dil = ndi.binary_dilation(mask, structure=_disk(width))
    ero = ndi.binary_erosion(mask, structure=_disk(width))
    return np.logical_and(dil, ~ero)

def _bbox(mask: np.ndarray):
    ys, xs = np.where(mask)
    if ys.size == 0:
        return (0, 0, mask.shape[0], mask.shape[1])
    return (ys.min(), xs.min(), ys.max() + 1, xs.max() + 1)

def _perimeter(mask: np.ndarray) -> float:
    edge = np.logical_and(mask, ~ndi.binary_erosion(mask))
    return float(edge.sum())

def _convex_area(mask: np.ndarray) -> float:
    ys, xs = np.where(mask)
    if xs.size < 3:
        return float(mask.sum())
    pts = np.column_stack((xs, ys))
    try:
        hull = ConvexHull(pts)
        return float(hull.volume)
    except Exception:
        return float(mask.sum())

def _moments_hu(mask: np.ndarray):
    y, x = np.indices(mask.shape, dtype=np.float64)
    m00 = mask.sum()
    if m00 == 0:
        return [np.nan] * 7
    m10 = (x * mask).sum()
    m01 = (y * mask).sum()
    cx = m10 / m00
    cy = m01 / m00
    x_c = x - cx
    y_c = y - cy
    mu20 = (x_c * x_c * mask).sum()
    mu02 = (y_c * y_c * mask).sum()
    mu11 = (x_c * y_c * mask).sum()
    mu30 = (x_c ** 3 * mask).sum()
    mu03 = (y_c ** 3 * mask).sum()
    mu21 = (x_c ** 2 * y_c * mask).sum()
    mu12 = (x_c * y_c ** 2 * mask).sum()

    def eta(p, q, mu_pq):
        return mu_pq / m00 ** (1 + (p + q) / 2.0)
    n20 = eta(2, 0, mu20)
    n02 = eta(0, 2, mu02)
    n11 = eta(1, 1, mu11)
    n30 = eta(3, 0, mu30)
    n03 = eta(0, 3, mu03)
    n21 = eta(2, 1, mu21)
    n12 = eta(1, 2, mu12)
    hu1 = n20 + n02
    hu2 = (n20 - n02) ** 2 + 4 * n11 ** 2
    hu3 = (n30 - 3 * n12) ** 2 + (3 * n21 - n03) ** 2
    hu4 = (n30 + n12) ** 2 + (n21 + n03) ** 2
    hu5 = (n30 - 3 * n12) * (n30 + n12) * ((n30 + n12) ** 2 - 3 * (n21 + n03) ** 2) + (3 * n21 - n03) * (n21 + n03) * (3 * (n30 + n12) ** 2 - (n21 + n03) ** 2)
    hu6 = (n20 - n02) * ((n30 + n12) ** 2 - (n21 + n03) ** 2) + 4 * n11 * (n30 + n12) * (n21 + n03)
    hu7 = (3 * n21 - n03) * (n30 + n12) * ((n30 + n12) ** 2 - 3 * (n21 + n03) ** 2) - (n30 - 3 * n12) * (n21 + n03) * (3 * (n30 + n12) ** 2 - (n21 + n03) ** 2)
    return [float(hu1), float(hu2), float(hu3), float(hu4), float(hu5), float(hu6), float(hu7)]

def shape_features(mask: np.ndarray, mm_row=np.nan, mm_col=np.nan):
    out = {k: np.nan for k in ['area', 'perimeter', 'convex_area', 'solidity', 'extent', 'eccentricity', 'aspect_ratio', 'compactness', 'circularity', 'hu1', 'hu2', 'hu3', 'hu4', 'hu5', 'hu6', 'hu7', 'area_mm2', 'perimeter_mm', 'equiv_diam_mm', 'major_axis_mm', 'minor_axis_mm']}
    if not mask.any():
        return out
    area = float(mask.sum())
    per = _perimeter(mask)
    c_area = _convex_area(mask)
    solidity = float(area / c_area) if c_area > 0 else np.nan
    y0, x0, y1, x1 = _bbox(mask)
    extent = float(area / ((y1 - y0) * (x1 - x0))) if y1 > y0 and x1 > x0 else np.nan
    ys, xs = np.where(mask)
    if xs.size >= 2:
        x_c = xs - xs.mean()
        y_c = ys - ys.mean()
        cov = np.cov(np.vstack((x_c, y_c)))
        eigvals, _ = np.linalg.eig(cov)
        eigvals = np.sort(np.abs(eigvals))[::-1]
        maj = float(np.sqrt(max(eigvals[0], 1e-12)) * 4.0)
        minr = float(np.sqrt(max(eigvals[-1], 1e-12)) * 4.0)
        aspect = maj / max(minr, 1e-12)
        ecc = float(np.sqrt(1.0 - (minr / maj) ** 2)) if maj > 0 else np.nan
    else:
        maj, minr, aspect, ecc = (np.nan, np.nan, np.nan, np.nan)
    compactness = per ** 2 / (4.0 * math.pi * area) if area > 0 and per > 0 else np.nan
    circularity = 4.0 * math.pi * area / per ** 2 if per > 0 and area > 0 else np.nan
    hu = _moments_hu(mask)
    if np.isfinite(mm_row) and np.isfinite(mm_col):
        area_mm2 = area * mm_row * mm_col
        s_mean = (mm_row + mm_col) / 2.0
        perimeter_mm = per * s_mean if per == per else np.nan
        equiv_diam_mm = math.sqrt(4.0 * area_mm2 / math.pi) if area_mm2 > 0 else np.nan
        major_axis_mm = maj * s_mean if maj == maj else np.nan
        minor_axis_mm = minr * s_mean if minr == minr else np.nan
    else:
        area_mm2 = perimeter_mm = equiv_diam_mm = major_axis_mm = minor_axis_mm = np.nan
    out.update(dict(area=area, perimeter=per, convex_area=c_area, solidity=solidity, extent=extent, eccentricity=ecc, aspect_ratio=aspect, compactness=compactness, circularity=circularity, hu1=hu[0], hu2=hu[1], hu3=hu[2], hu4=hu[3], hu5=hu[4], hu6=hu[5], hu7=hu[6], area_mm2=area_mm2, perimeter_mm=perimeter_mm, equiv_diam_mm=equiv_diam_mm, major_axis_mm=major_axis_mm, minor_axis_mm=minor_axis_mm))
    return out

def margin_edge_features(g: np.ndarray, mask: np.ndarray):
    gx = ndi.sobel(g, axis=1, mode='nearest')
    gy = ndi.sobel(g, axis=0, mode='nearest')
    gm = np.hypot(gx, gy)
    band = boundary_band(mask, width=2)
    core = ndi.binary_erosion(mask, structure=_disk(2))
    core = np.logical_and(mask, core)
    edge_vals = gm[band]
    core_vals = gm[core]
    edge_sharp = float(np.nan) if edge_vals.size == 0 else float(edge_vals.mean())
    core_grad = float(np.nan) if core_vals.size == 0 else float(core_vals.mean())
    sharp_ratio = float(np.nan) if not np.isfinite(core_grad) else float(edge_sharp / (core_grad + 1e-08))
    per = _perimeter(mask)
    conv_mask = ndi.binary_dilation(mask, structure=_disk(5))
    conv_per = _perimeter(conv_mask)
    irregularity = float(per / conv_per) if conv_per > 0 and per > 0 else np.nan
    spic_idx = np.nan
    try:
        ys, xs = np.where(mask)
        if ys.size > 0:
            cy, cx = (ys.mean(), xs.mean())
            yy, xx = np.where(band)
            if yy.size > 0:
                vy = yy - cy
                vx = xx - cx
                vnorm = np.hypot(vx, vy) + 1e-08
                vx /= vnorm
                vy /= vnorm
                gx_b = gx[yy, xx]
                gy_b = gy[yy, xx]
                gnorm = np.hypot(gx_b, gy_b) + 1e-08
                gx_b /= gnorm
                gy_b /= gnorm
                cosang = gx_b * vx + gy_b * vy
                spic_idx = float(np.mean(np.clip(cosang, 0, 1)))
    except Exception:
        pass
    return dict(edge_sharpness=edge_sharp, core_gradient=core_grad, sharpness_ratio=sharp_ratio, boundary_irregularity=irregularity, spiculation_index=spic_idx)

def _glcm_props(gq: np.ndarray, mask: np.ndarray, levels: int, offsets):
    props_acc = dict(contrast=0.0, dissimilarity=0.0, homogeneity=0.0, energy=0.0, ASM=0.0, correlation=0.0)
    count = 0
    H, W = gq.shape
    gq = gq.astype(np.int32, copy=False)
    mask = mask.astype(bool, copy=False)
    for dy, dx in offsets:
        y0A, y1A = (max(0, dy), H + min(0, dy))
        x0A, x1A = (max(0, dx), W + min(0, dx))
        y0B, y1B = (max(0, -dy), H - max(0, dy))
        x0B, x1B = (max(0, -dx), W - max(0, dx))
        A = gq[y0A:y1A, x0A:x1A]
        B = gq[y0B:y1B, x0B:x1B]
        MA = mask[y0A:y1A, x0A:x1A]
        MB = mask[y0B:y1B, x0B:x1B]
        if A.size == 0 or B.size == 0:
            continue
        M = MA & MB
        if not M.any():
            continue
        A = A[M]
        B = B[M]
        P = np.zeros((levels, levels), dtype=np.float64)
        np.add.at(P, (A, B), 1)
        np.add.at(P, (B, A), 1)
        s = P.sum()
        if s <= 0:
            continue
        P /= s
        i = np.arange(levels)
        j = np.arange(levels)
        ii, jj = np.meshgrid(i, j, indexing='ij')
        pi = P.sum(axis=1)
        pj = P.sum(axis=0)
        mu_i = (pi * i).sum()
        mu_j = (pj * j).sum()
        si = np.sqrt((pi * (i - mu_i) ** 2).sum() + 1e-12)
        sj = np.sqrt((pj * (j - mu_j) ** 2).sum() + 1e-12)
        props_acc['contrast'] += ((ii - jj) ** 2 * P).sum()
        props_acc['dissimilarity'] += (np.abs(ii - jj) * P).sum()
        props_acc['homogeneity'] += (P / (1.0 + (ii - jj) ** 2)).sum()
        props_acc['energy'] += np.sqrt((P ** 2).sum())
        props_acc['ASM'] += (P ** 2).sum()
        props_acc['correlation'] += ((ii - mu_i) * (jj - mu_j) * P).sum() / (si * sj)
        count += 1
    if count == 0:
        return {k: np.nan for k in ['glcm_contrast', 'glcm_dissimilarity', 'glcm_homogeneity', 'glcm_energy', 'glcm_ASM', 'glcm_correlation']}
    for k in list(props_acc.keys()):
        props_acc[k] /= count
    return {'glcm_contrast': float(props_acc['contrast']), 'glcm_dissimilarity': float(props_acc['dissimilarity']), 'glcm_homogeneity': float(props_acc['homogeneity']), 'glcm_energy': float(props_acc['energy']), 'glcm_ASM': float(props_acc['ASM']), 'glcm_correlation': float(props_acc['correlation'])}

def glcm_features(g: np.ndarray, mask: np.ndarray, levels: int=32):
    roi_vals = g[mask]
    if roi_vals.size == 0:
        return {k: np.nan for k in ['glcm_contrast', 'glcm_dissimilarity', 'glcm_homogeneity', 'glcm_energy', 'glcm_ASM', 'glcm_correlation']}
    lo, hi = np.percentile(roi_vals, [1, 99])
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo, hi = (float(roi_vals.min()), float(roi_vals.max()))
        if hi <= lo:
            hi = lo + 1e-06
    gq = ((np.clip(g, lo, hi) - lo) / (hi - lo + 1e-12) * (levels - 1)).astype(np.int32)
    offsets = []
    for d in [1, 2, 3]:
        offsets += [(0, d), (d, 0), (d, d), (d, -d)]
    return _glcm_props(gq, mask, levels, offsets)

def lbp_uniform(g: np.ndarray, P=8, R=1):
    H, W = g.shape
    angles = np.arange(P) * (2.0 * np.pi / P)
    dy = -np.round(R * np.sin(angles)).astype(int)
    dx = np.round(R * np.cos(angles)).astype(int)
    L = np.zeros_like(g, dtype=np.uint8)
    for p in range(P):
        shifted = np.zeros_like(g, dtype=g.dtype)
        y0 = max(0, dy[p])
        y1 = H + min(0, dy[p])
        x0 = max(0, dx[p])
        x1 = W + min(0, dx[p])
        shifted[y0:y1, x0:x1] = g[y0 - dy[p]:y1 - dy[p], x0 - dx[p]:x1 - dx[p]]
        L |= (shifted >= g).astype(np.uint8) << p

    def transitions(code):
        bits = (code << 1 | code >> P - 1) & (1 << P) - 1
        x = code ^ bits
        return bin(x).count('1')
    lut = np.zeros(1 << P, dtype=np.uint8)
    uni_idx = 0
    for code in range(1 << P):
        if transitions(code) <= 2:
            lut[code] = uni_idx
            uni_idx += 1
        else:
            lut[code] = P + 1
    L = lut[L]
    return L

def lbp_features(g: np.ndarray, mask: np.ndarray, P=8, R=1):
    try:
        L = lbp_uniform(g, P=P, R=R)
        L = L[mask]
        n_bins = P + 2
        hist, _ = np.histogram(L, bins=np.arange(0, n_bins + 1), range=(0, n_bins), density=True)
        return {f'lbp_u{P}_r{R}_b{i}': float(hist[i]) for i in range(n_bins)}
    except Exception:
        return {f'lbp_u{P}_r{R}_b{i}': np.nan for i in range(P + 2)}

def _gabor_kernel(theta, freq, size=9, sigma=None):
    if sigma is None:
        sigma = max(1.0, 0.5 / freq)
    r = size // 2
    y, x = np.mgrid[-r:r + 1, -r:r + 1]
    xr = x * np.cos(theta) + y * np.sin(theta)
    yr = -x * np.sin(theta) + y * np.cos(theta)
    gauss = np.exp(-(xr ** 2 + yr ** 2) / (2 * sigma * sigma))
    real = gauss * np.cos(2 * np.pi * freq * xr)
    imag = gauss * np.sin(2 * np.pi * freq * xr)
    return (real, imag)

def gabor_features(g: np.ndarray, mask: np.ndarray):
    thetas = [0, np.pi / 4, np.pi / 2, 3 * np.pi / 4]
    freqs = [0.2, 0.4]
    vals = []
    for f in freqs:
        for th in thetas:
            kr, ki = _gabor_kernel(th, f, size=11)
            try:
                rr = ndi.convolve(g, kr, mode='nearest')
                ii = ndi.convolve(g, ki, mode='nearest')
                amp = np.sqrt(rr ** 2 + ii ** 2)
                vals.append(float(np.mean(amp[mask])))
            except Exception:
                vals.append(np.nan)
    arr = np.array(vals, dtype=float)
    return dict(gabor_mean=float(np.nanmean(arr)), gabor_std=float(np.nanstd(arr)))

def calcification_proxy(g: np.ndarray, mask: np.ndarray):
    try:
        roi = g.copy()
        roi[~mask] = np.nan
        vals = roi[mask]
        if vals.size == 0:
            return dict(calc_blob_count=np.nan, calc_radius_mean=np.nan, calc_radius_std=np.nan, calc_nn_dist_mean=np.nan)
        thr = np.nanpercentile(vals, 99.0)
        bright = np.zeros_like(roi, dtype=bool)
        bright[mask] = roi[mask] >= thr
        lbl, n = ndi.label(bright)
        if n == 0:
            return dict(calc_blob_count=0, calc_radius_mean=np.nan, calc_radius_std=np.nan, calc_nn_dist_mean=np.nan)
        sizes = ndi.sum(np.ones_like(lbl), lbl, index=range(1, n + 1))
        idx_keep = [i + 1 for i, s in enumerate(sizes) if s <= 30]
        if len(idx_keep) == 0:
            return dict(calc_blob_count=0, calc_radius_mean=np.nan, calc_radius_std=np.nan, calc_nn_dist_mean=np.nan)
        radii = []
        centers = []
        for labv in idx_keep:
            yy, xx = np.where(lbl == labv)
            a = float(len(yy))
            r = math.sqrt(a / math.pi)
            radii.append(r)
            centers.append([yy.mean(), xx.mean()])
        radii = np.array(radii, dtype=float)
        centers = np.array(centers, dtype=float)
        nn = np.nan
        if centers.shape[0] >= 2:
            dmins = []
            for i in range(centers.shape[0]):
                d = np.sqrt(np.sum((centers[i] - centers[np.arange(centers.shape[0]) != i]) ** 2, axis=1))
                dmins.append(d.min())
            nn = float(np.mean(dmins))
        return dict(calc_blob_count=int(len(radii)), calc_radius_mean=float(np.nanmean(radii)) if radii.size else np.nan, calc_radius_std=float(np.nanstd(radii)) if radii.size else np.nan, calc_nn_dist_mean=float(nn))
    except Exception:
        return dict(calc_blob_count=np.nan, calc_radius_mean=np.nan, calc_radius_std=np.nan, calc_nn_dist_mean=np.nan)

def basic_intensity_stats(g: np.ndarray, mask: np.ndarray):
    roi = g[mask]
    if roi.size == 0:
        return dict(int_mean=np.nan, int_std=np.nan, int_median=np.nan, int_p10=np.nan, int_p90=np.nan, int_iqr=np.nan)
    q10, q90 = np.percentile(roi, [10, 90])
    q25, q75 = np.percentile(roi, [25, 75])
    return dict(int_mean=float(roi.mean()), int_std=float(roi.std(ddof=0)), int_median=float(np.median(roi)), int_p10=float(q10), int_p90=float(q90), int_iqr=float(q75 - q25))

def extract_single_features_from_row(row: pd.Series) -> dict:
    out = {}
    roi, meta, err = _load_roi_from_row(row)
    if roi is None:
        out['__error__'] = err if err else 'roi_load_failed'
        return out
    g = ndi.gaussian_filter(roi, sigma=0.8).astype(np.float32, copy=False)
    m = segment_lesion_mask(g)
    mm_row, mm_col = _pixel_spacing_mm(meta)
    out.update(basic_intensity_stats(g, m))
    out.update(shape_features(m, mm_row, mm_col))
    out.update(margin_edge_features(g, m))
    out.update(glcm_features(g, m))
    out.update(lbp_features(g, m, P=8, R=1))
    out.update(gabor_features(g, m))
    out.update(calcification_proxy(g, m))
    out['roi_h'] = int(g.shape[0])
    out['roi_w'] = int(g.shape[1])
    out['mask_frac'] = float(np.mean(m)) if m.size > 0 else np.nan
    out['pixsp_row_mm'] = float(mm_row) if np.isfinite(mm_row) else np.nan
    out['pixsp_col_mm'] = float(mm_col) if np.isfinite(mm_col) else np.nan
    return out

def main():
    if not os.path.isfile(INPUT_CSV):
        raise FileNotFoundError(f'INPUT_CSV not found: {INPUT_CSV}')
    df = pd.read_csv(INPUT_CSV, low_memory=False)
    if not any((c in df.columns for c in ['lesion_npy', 'lesion_image'])):
        raise KeyError('CSV must contain at least one of: lesion_npy or lesion_image')
    _log(f'Rows to process: {len(df)}')
    rows = []
    for i, row in df.iterrows():
        try:
            feats = extract_single_features_from_row(row)
        except Exception as e:
            feats = {'__error__': f'row_failed: {e}'}
        rows.append(feats)
        if VERBOSE and ((i + 1) % 50 == 0 or i + 1 == len(df)):
            _log(f' processed {i + 1}/{len(df)}')
    feats_df = pd.DataFrame(rows).add_prefix('feat_')
    out_df = pd.concat([df.reset_index(drop=True), feats_df.reset_index(drop=True)], axis=1)
    os.makedirs(os.path.dirname(OUTPUT_CSV) or '.', exist_ok=True)
    out_df.to_csv(OUTPUT_CSV, index=False)
    _log(f'Saved single-image features → {OUTPUT_CSV}')
    err_col = 'feat___error__'
    if err_col in out_df.columns:
        n_err = int(out_df[err_col].notna().sum())
        if n_err:
            _log(f'Completed with {n_err} rows reporting __error__ (check ROI cache paths).')

def run_single_features_safe(input_csv: str, output_csv: str, verbose: bool=True, log_file: Optional[str]=None) -> str:
    if not isinstance(input_csv, str) or not input_csv:
        return '[error] input_csv must be a non-empty string'
    if not os.path.isfile(input_csv):
        return f'[error] input_csv does not exist: {input_csv}'
    if not isinstance(output_csv, str) or not output_csv:
        return '[error] output_csv must be a non-empty string'
    try:
        head = pd.read_csv(input_csv, nrows=5, low_memory=False)
    except Exception as e:
        return f'[error] failed to read CSV head: {e}'
    if not any((c in head.columns for c in ['lesion_npy', 'lesion_image'])):
        return '[error] CSV must contain at least one of: lesion_npy or lesion_image'
    set_input_csv(input_csv)
    set_output_csv(output_csv)
    set_verbose(verbose)
    if log_file is None:
        out_dir = os.path.dirname(output_csv) or '.'
        os.makedirs(out_dir, exist_ok=True)
        log_file = os.path.join(out_dir, 'stage2_features.log')
    try:
        with open(log_file, 'w', encoding='utf-8') as fp:
            tee_out = _Tee(fp, sys.__stdout__)
            tee_err = _Tee(fp, sys.__stderr__)
            old_out, old_err = (sys.stdout, sys.stderr)
            sys.stdout, sys.stderr = (tee_out, tee_err)
            try:
                print(f'[info] Starting Stage 2 feature extraction')
                print(f'[info] input_csv={INPUT_CSV}')
                print(f'[info] output_csv={OUTPUT_CSV}')
                print(f'[info] verbose={VERBOSE}')
                main()
                print('[info] Stage 2 finished.')
            except Exception as e:
                print(f'[error] Stage 2 failed: {e}')
                return f'[error] Stage 2 failed: {e}'
            finally:
                sys.stdout, sys.stderr = (old_out, old_err)
    except Exception as e:
        try:
            main()
            return f'[warn] Logging failed ({e}); Stage 2 finished without tee. Output CSV: {output_csv}'
        except Exception as e2:
            return f'[error] Stage 2 failed (and logging failed): {e2}'
    return f'FINISHED: wrote {output_csv}. Log: {log_file}'
