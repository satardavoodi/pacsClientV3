# Imported inference implementation; provenance in ../provenance.json.
import os, json, warnings, sys
from typing import Tuple, Optional, Dict
import numpy as np
np.seterr(divide='ignore', invalid='ignore', over='ignore', under='ignore')
import pandas as pd
import itk
from scipy import ndimage as ndi
INPUT_CSV = ''
OUTPUT_CSV = ''
STUDY_COL = 'study_instance_uid'
LAT_COL = 'laterality'
VIEW_COL = 'view_position'
IMG_FULL = 'full_image_path'
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

def get_stage3_outputs() -> Dict[str, str]:
    return {'output_csv': OUTPUT_CSV}

def _log(m):
    if VERBOSE:
        print(m)

def _load_meta(path: str) -> dict:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _load_roi_from_row(row: pd.Series) -> Optional[np.ndarray]:
    npy_path = str(row.get('lesion_npy', '')).strip()
    if npy_path and os.path.isfile(npy_path):
        try:
            return np.load(npy_path).astype(np.float32, copy=False)
        except Exception:
            pass
    png_path = str(row.get('lesion_image', '')).strip()
    if png_path and os.path.isfile(png_path):
        try:
            im = itk.imread(png_path)
            arr = itk.GetArrayFromImage(im)
            if arr.ndim == 3:
                arr = arr[0]
            arr = arr.astype(np.float32, copy=False)
            meta_path = str(row.get('lesion_meta', '')).strip()
            vmin = vmax = None
            if meta_path and os.path.isfile(meta_path):
                meta = _load_meta(meta_path)
                vmin = float(meta.get('png_u16_linear_min', np.nan))
                vmax = float(meta.get('png_u16_linear_max', np.nan))
            if vmin is not None and vmax is not None and np.isfinite(vmin) and np.isfinite(vmax) and (vmax > vmin):
                roi = arr / 65535.0 * (vmax - vmin) + vmin
                return roi.astype(np.float32, copy=False)
            a_min, a_max = (float(np.nanmin(arr)), float(np.nanmax(arr)))
            if a_max > a_min:
                arr = (arr - a_min) / (a_max - a_min)
            return arr.astype(np.float32, copy=False)
        except Exception:
            return None
    return None

def _read_dicom_float(path: str) -> Optional[np.ndarray]:
    try:
        im = itk.imread(path, itk.F)
        arr = itk.GetArrayFromImage(im)
        if arr.ndim == 3:
            arr = arr[0]
        return arr.astype(np.float32, copy=False)
    except Exception:
        return None

def _norm_view(v: str) -> str:
    if not isinstance(v, str):
        return ''
    v = v.strip().upper()
    if 'CC' in v:
        return 'CC'
    if 'MLO' in v:
        return 'MLO'
    return v

def _norm_lat(v: str) -> str:
    if not isinstance(v, str):
        return ''
    v = v.strip().upper()
    if v.startswith('L'):
        return 'L'
    if v.startswith('R'):
        return 'R'
    return v

def _resize_to(a: np.ndarray, shape_hw: Tuple[int, int]) -> np.ndarray:
    Ha, Wa = a.shape
    Ht, Wt = (int(shape_hw[0]), int(shape_hw[1]))
    if Ha == Ht and Wa == Wt:
        return a.astype(np.float32, copy=False)
    zy = Ht / max(Ha, 1)
    zx = Wt / max(Wa, 1)
    return ndi.zoom(a, (zy, zx), order=1, mode='nearest').astype(np.float32, copy=False)

def _resize_pair_to_min(a: np.ndarray, b: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    Ha, Wa = a.shape
    Hb, Wb = b.shape
    Ht, Wt = (min(Ha, Hb), min(Wa, Wb))
    if Ht <= 0 or Wt <= 0:
        return (a, b)
    return (_resize_to(a, (Ht, Wt)), _resize_to(b, (Ht, Wt)))

def _ssim(a: np.ndarray, b: np.ndarray) -> float:
    try:
        a = a.astype(np.float32, copy=False)
        b = b.astype(np.float32, copy=False)
        finite = np.isfinite(a) & np.isfinite(b)
        if not finite.any():
            return np.nan
        a = np.where(finite, a, np.nanmean(a))
        b = np.where(finite, b, np.nanmean(b))
        a_min, a_max = (float(np.nanmin(a)), float(np.nanmax(a)))
        b_min, b_max = (float(np.nanmin(b)), float(np.nanmax(b)))
        L = max(a_max, b_max) - min(a_min, b_min)
        if not np.isfinite(L) or L <= 0:
            L = 1.0
        C1 = (0.01 * L) ** 2
        C2 = (0.03 * L) ** 2
        sigma = 1.5
        mu_a = ndi.gaussian_filter(a, sigma=sigma)
        mu_b = ndi.gaussian_filter(b, sigma=sigma)
        mu_a2, mu_b2, mu_ab = (mu_a * mu_a, mu_b * mu_b, mu_a * mu_b)
        sigma_a2 = ndi.gaussian_filter(a * a, sigma=sigma) - mu_a2
        sigma_b2 = ndi.gaussian_filter(b * b, sigma=sigma) - mu_b2
        sigma_ab = ndi.gaussian_filter(a * b, sigma=sigma) - mu_ab
        with np.errstate(divide='ignore', invalid='ignore', over='ignore', under='ignore'):
            num = (2 * mu_ab + C1) * (2 * sigma_ab + C2)
            den = (mu_a2 + mu_b2 + C1) * (sigma_a2 + sigma_b2 + C2)
            ssim_map = num / (den + 1e-12)
            return float(np.nanmean(ssim_map))
    except Exception:
        return np.nan

def _safe_pearson(a: np.ndarray, b: np.ndarray) -> float:
    try:
        va = a.reshape(-1).astype(np.float32, copy=False)
        vb = b.reshape(-1).astype(np.float32, copy=False)
        mask = np.isfinite(va) & np.isfinite(vb)
        if mask.sum() < 2:
            return np.nan
        va = va[mask]
        vb = vb[mask]
        va -= va.mean()
        vb -= vb.mean()
        sa = va.std()
        sb = vb.std()
        if not np.isfinite(sa) or not np.isfinite(sb) or sa == 0.0 or (sb == 0.0):
            return np.nan
        with np.errstate(divide='ignore', invalid='ignore', over='ignore', under='ignore'):
            return float((va * vb).mean() / (sa * sb))
    except Exception:
        return np.nan

def _pair_similarity(a: np.ndarray, b: np.ndarray) -> dict:
    try:
        a, b = _resize_pair_to_min(a, b)
        return {'ssim': _ssim(a, b), 'ncc': _safe_pearson(a, b)}
    except Exception:
        return {'ssim': np.nan, 'ncc': np.nan}

def _basic_stats(g: np.ndarray) -> dict:
    g = g.astype(np.float32, copy=False)
    gv = g.reshape(-1)
    gv = gv[np.isfinite(gv)]
    if gv.size == 0:
        return dict(mean=np.nan, median=np.nan, p90=np.nan, iqr=np.nan)
    q10, q25, q75, q90 = np.percentile(gv, [10, 25, 75, 90])
    return dict(mean=float(np.mean(gv)), median=float(np.median(gv)), p90=float(q90), iqr=float(q75 - q25))

def _lbp_vec_from_row(row: pd.Series, P=8, R=1):
    n_bins = P + 2
    v = np.array([row.get(f'feat_lbp_u{P}_r{R}_b{i}', np.nan) for i in range(n_bins)], dtype=float)
    return v if np.isfinite(v).all() else None

def _cosine(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> float:
    if a is None or b is None or a.shape != b.shape:
        return np.nan
    na, nb = (np.linalg.norm(a), np.linalg.norm(b))
    if na == 0 or nb == 0:
        return np.nan
    return float(np.dot(a, b) / (na * nb))

def _pick_cc_mlo_opposite(group_df: pd.DataFrame, view_value: str, this_row: pd.Series) -> Optional[pd.Series]:
    opp_view = 'MLO' if view_value == 'CC' else 'CC'
    opp = group_df[group_df[VIEW_COL] == opp_view]
    if opp.empty:
        return None
    if 'finding_categories' in group_df.columns and isinstance(this_row.get('finding_categories', None), str):
        this_fc = set((x.strip() for x in this_row['finding_categories'].strip('[]').replace("'", '').split(',') if x.strip()))

        def overlap(s):
            if not isinstance(s, str):
                return 0
            oth = set((x.strip() for x in s.strip('[]').replace("'", '').split(',') if x.strip()))
            return len(this_fc & oth)
        opp = opp.copy()
        opp['__ov__'] = opp['finding_categories'].apply(overlap)
        opp = opp.sort_values(['__ov__']).iloc[::-1]
        best = opp.iloc[0]
        if best['__ov__'] > 0:
            return best.drop(labels='__ov__')
    return opp.sort_index().iloc[0]

def _pick_contralateral_roi_row(df: pd.DataFrame, sid, view: str, laterality: str) -> Optional[pd.Series]:
    opp_lat = 'L' if laterality == 'R' else 'R'
    cand = df[(df[STUDY_COL] == sid) & (df[VIEW_COL] == view) & (df[LAT_COL] == opp_lat)]
    if cand.empty:
        return None
    has_roi = cand[cand['lesion_npy'].notna() | cand['lesion_image'].notna()]
    if not has_roi.empty:
        return has_roi.sort_index().iloc[0]
    return cand.sort_index().iloc[0]

def _mirror_crop_from_contra(full_dcm_path: str, this_meta: dict) -> Optional[np.ndarray]:
    try:
        if not isinstance(this_meta, dict):
            return None
        box = this_meta.get('box_dicom', {})
        x0 = int(box.get('x0', -1))
        y0 = int(box.get('y0', -1))
        x1 = int(box.get('x1', -1))
        y1 = int(box.get('y1', -1))
        if x0 < 0 or y0 < 0 or x1 <= x0 or (y1 <= y0):
            return None
        contra = _read_dicom_float(full_dcm_path)
        if contra is None:
            return None
        Hc, Wc = contra.shape
        mx0 = Wc - x1
        mx1 = Wc - x0
        mx0 = max(0, min(Wc - 1, mx0))
        mx1 = max(1, min(Wc, mx1))
        y0c = max(0, min(Hc - 1, y0))
        y1c = max(1, min(Hc, y1))
        if mx1 <= mx0 or y1c <= y0c:
            return None
        patch = contra[y0c:y1c, mx0:mx1]
        if patch.size == 0:
            return None
        return patch.astype(np.float32, copy=False)
    except Exception:
        return None

def main():
    if not os.path.isfile(INPUT_CSV):
        raise FileNotFoundError(f'INPUT_CSV not found: {INPUT_CSV}')
    df = pd.read_csv(INPUT_CSV, low_memory=False)
    for col in (STUDY_COL, LAT_COL, VIEW_COL):
        if col not in df.columns:
            raise KeyError(f'Missing required column: {col}')
    df[VIEW_COL] = df[VIEW_COL].astype(str).map(_norm_view)
    df[LAT_COL] = df[LAT_COL].astype(str).map(_norm_lat)
    mv_init = {'mv_ssim': np.nan, 'mv_ncc': np.nan, 'mv_pair_found': False, 'mv_pair_view': '', 'mv_pair_row_index': np.nan}
    for k, v in mv_init.items():
        if k not in df.columns:
            df[k] = v
    df['mv_pair_view'] = df['mv_pair_view'].astype(object)
    mv_scalar_names = ['int_mean', 'int_median', 'int_std', 'area', 'eccentricity', 'circularity', 'compactness', 'aspect_ratio', 'solidity', 'boundary_irregularity', 'gabor_mean', 'gabor_std', 'glcm_contrast', 'glcm_homogeneity', 'glcm_energy', 'glcm_ASM', 'glcm_correlation', 'glcm_dissimilarity', 'calc_blob_count', 'calc_radius_mean', 'calc_radius_std', 'calc_nn_dist_mean', 'area_mm2', 'perimeter_mm', 'equiv_diam_mm', 'major_axis_mm', 'minor_axis_mm']
    for nm in mv_scalar_names:
        col = f'mv_{nm}_absdiff'
        if col not in df.columns:
            df[col] = np.nan
    if all((f'feat_lbp_u8_r1_b{i}' in df.columns for i in range(10))) and 'mv_lbp_cosine' not in df.columns:
        df['mv_lbp_cosine'] = np.nan
    bl_init = {'bl_pair_found': False, 'bl_pair_row_index': np.nan, 'bl_source': 'none', 'bl_ssim': np.nan, 'bl_ncc': np.nan, 'bl_mean_ratio': np.nan, 'bl_median_ratio': np.nan, 'bl_p90_diff': np.nan, 'bl_iqr_diff': np.nan}
    for k, v in bl_init.items():
        if k not in df.columns:
            df[k] = v
    df['bl_source'] = df['bl_source'].astype(object)
    bl_scalar_names = ['int_mean', 'int_median', 'int_std', 'area', 'eccentricity', 'circularity', 'compactness', 'aspect_ratio', 'solidity', 'gabor_mean', 'gabor_std', 'glcm_contrast', 'glcm_homogeneity', 'glcm_energy', 'glcm_ASM', 'glcm_correlation', 'glcm_dissimilarity', 'area_mm2', 'perimeter_mm', 'equiv_diam_mm', 'major_axis_mm', 'minor_axis_mm']
    for nm in bl_scalar_names:
        col = f'bl_{nm}_absdiff'
        if col not in df.columns:
            df[col] = np.nan
    if all((f'feat_lbp_u8_r1_b{i}' in df.columns for i in range(10))) and 'bl_lbp_cosine' not in df.columns:
        df['bl_lbp_cosine'] = np.nan
    grouped_same_side = df.groupby([STUDY_COL, LAT_COL], dropna=False)
    total = len(df)
    done = 0
    for (sid, lat), g in grouped_same_side:
        g = g.copy()
        for idx, row in g.iterrows():
            try:
                view = row[VIEW_COL]
                if view not in ('CC', 'MLO'):
                    continue
                opp_row = _pick_cc_mlo_opposite(g, view, row)
                if opp_row is not None:
                    a = _load_roi_from_row(row)
                    b = _load_roi_from_row(opp_row)
                    if a is not None and b is not None:
                        sim = _pair_similarity(a, b)
                        df.at[idx, 'mv_ssim'] = sim['ssim']
                        df.at[idx, 'mv_ncc'] = sim['ncc']
                        df.at[idx, 'mv_pair_found'] = True
                        df.at[idx, 'mv_pair_view'] = 'MLO' if view == 'CC' else 'CC'
                        df.at[idx, 'mv_pair_row_index'] = float(opp_row.name)
                        for nm in mv_scalar_names:
                            fa = row.get(f'feat_{nm}', np.nan)
                            fb = opp_row.get(f'feat_{nm}', np.nan)
                            if pd.notna(fa) and pd.notna(fb):
                                df.at[idx, f'mv_{nm}_absdiff'] = float(abs(fa - fb))
                        if 'mv_lbp_cosine' in df.columns:
                            va = _lbp_vec_from_row(row, P=8, R=1)
                            vb = _lbp_vec_from_row(opp_row, P=8, R=1)
                            df.at[idx, 'mv_lbp_cosine'] = _cosine(va, vb)
                contra_row = _pick_contralateral_roi_row(df, sid, view, lat)
                contra_used = 'none'
                contr_roi = None
                if contra_row is not None:
                    contr_roi = _load_roi_from_row(contra_row)
                    if contr_roi is not None:
                        contra_used = 'roi'
                    else:
                        meta_path = str(row.get('lesion_meta', '')).strip()
                        this_meta = _load_meta(meta_path) if meta_path and os.path.isfile(meta_path) else {}
                        full_contra_path = str(contra_row.get(IMG_FULL, '')).strip()
                        if full_contra_path and os.path.isfile(full_contra_path):
                            contr_roi = _mirror_crop_from_contra(full_contra_path, this_meta)
                            if contr_roi is not None:
                                contra_used = 'mirrored'
                if contr_roi is not None:
                    this_roi = _load_roi_from_row(row)
                    if this_roi is not None:
                        sim = _pair_similarity(this_roi, contr_roi)
                        df.at[idx, 'bl_ssim'] = sim['ssim']
                        df.at[idx, 'bl_ncc'] = sim['ncc']
                        a_stats = _basic_stats(this_roi)
                        b_stats = _basic_stats(contr_roi)
                        if pd.notna(a_stats['mean']) and pd.notna(b_stats['mean']) and (b_stats['mean'] != 0):
                            df.at[idx, 'bl_mean_ratio'] = float(a_stats['mean'] / (b_stats['mean'] + 1e-08))
                        if pd.notna(a_stats['median']) and pd.notna(b_stats['median']) and (b_stats['median'] != 0):
                            df.at[idx, 'bl_median_ratio'] = float(a_stats['median'] / (b_stats['median'] + 1e-08))
                        if pd.notna(a_stats['p90']) and pd.notna(b_stats['p90']):
                            df.at[idx, 'bl_p90_diff'] = float(a_stats['p90'] - b_stats['p90'])
                        if pd.notna(a_stats['iqr']) and pd.notna(b_stats['iqr']):
                            df.at[idx, 'bl_iqr_diff'] = float(a_stats['iqr'] - b_stats['iqr'])
                        if contra_used == 'roi':
                            for nm in bl_scalar_names:
                                fa = row.get(f'feat_{nm}', np.nan)
                                fb = contra_row.get(f'feat_{nm}', np.nan)
                                if pd.notna(fa) and pd.notna(fb):
                                    df.at[idx, f'bl_{nm}_absdiff'] = float(abs(fa - fb))
                            if 'bl_lbp_cosine' in df.columns:
                                va = _lbp_vec_from_row(row, P=8, R=1)
                                vb = _lbp_vec_from_row(contra_row, P=8, R=1)
                                df.at[idx, 'bl_lbp_cosine'] = _cosine(va, vb)
                        df.at[idx, 'bl_pair_found'] = True
                        df.at[idx, 'bl_pair_row_index'] = float(contra_row.name)
                        df.at[idx, 'bl_source'] = contra_used
                done += 1
                if VERBOSE and done % 250 == 0:
                    _log(f' processed {done}/{total}')
            except Exception as e:
                _log(f'[warn] row {idx} failed: {e}')
    os.makedirs(os.path.dirname(OUTPUT_CSV) or '.', exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    _log(f'Saved multi-view + bilateral features → {OUTPUT_CSV}')

def run_multiview_bilateral_safe(input_csv: str, output_csv: str, verbose: bool=True, log_file: Optional[str]=None) -> str:
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
    for col in (STUDY_COL, LAT_COL, VIEW_COL):
        if col not in head.columns:
            return f'[error] missing required column: {col}'
    if not any((c in head.columns for c in ['lesion_npy', 'lesion_image'])):
        return '[error] CSV must contain at least one ROI column: lesion_npy or lesion_image'
    set_input_csv(input_csv)
    set_output_csv(output_csv)
    set_verbose(verbose)
    if log_file is None:
        out_dir = os.path.dirname(output_csv) or '.'
        os.makedirs(out_dir, exist_ok=True)
        log_file = os.path.join(out_dir, 'stage3_multiview.log')
    try:
        with open(log_file, 'w', encoding='utf-8') as fp:
            tee_out = _Tee(fp, sys.__stdout__)
            tee_err = _Tee(fp, sys.__stderr__)
            old_out, old_err = (sys.stdout, sys.stderr)
            sys.stdout, sys.stderr = (tee_out, tee_err)
            try:
                print(f'[info] Starting Stage 3 multi-view/bilateral features')
                print(f'[info] input_csv={INPUT_CSV}')
                print(f'[info] output_csv={OUTPUT_CSV}')
                print(f'[info] verbose={VERBOSE}')
                main()
                print('[info] Stage 3 finished.')
            except Exception as e:
                print(f'[error] Stage 3 failed: {e}')
                return f'[error] Stage 3 failed: {e}'
            finally:
                sys.stdout, sys.stderr = (old_out, old_err)
    except Exception as e:
        try:
            main()
            return f'[warn] Logging failed ({e}); Stage 3 finished without tee. Output CSV: {output_csv}'
        except Exception as e2:
            return f'[error] Stage 3 failed (and logging failed): {e2}'
    return f'FINISHED: wrote {output_csv}. Log: {log_file}'
