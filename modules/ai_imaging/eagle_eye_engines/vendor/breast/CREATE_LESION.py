# Imported inference implementation; provenance in ../provenance.json.
import os, json, math, warnings, random, sys
from pathlib import Path
from typing import Tuple, Optional, Dict
import numpy as np
import pandas as pd
import itk
import pydicom
INPUT_CSV = ''
OUTPUT_CSV = ''
ROI_ROOT = ''
SAVE_PNG16 = True
SAVE_NPY = True
PNG_SUFFIX = '.png'
VERBOSE = True
RNG_SEED = 1337
warnings.filterwarnings('ignore', category=UserWarning)
if ROI_ROOT:
    os.makedirs(ROI_ROOT, exist_ok=True)
random.seed(RNG_SEED)
np.random.seed(RNG_SEED)

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

def set_roi_root(path: str):
    global ROI_ROOT
    ROI_ROOT = str(path)
    os.makedirs(ROI_ROOT, exist_ok=True)

def set_save_flags(save_png16: bool=True, save_npy: bool=True, verbose: bool=True):
    global SAVE_PNG16, SAVE_NPY, VERBOSE
    SAVE_PNG16 = bool(save_png16)
    SAVE_NPY = bool(save_npy)
    VERBOSE = bool(verbose)

def get_stage1_outputs() -> Dict[str, str]:
    return {'output_csv': OUTPUT_CSV, 'roi_root': ROI_ROOT}

def _log(msg: str):
    if VERBOSE:
        print(msg)

def _safe_float(x, default=np.nan):
    try:
        return float(x)
    except Exception:
        return default

def _is_finite_box(x0, y0, x1, y1):
    vals = [x0, y0, x1, y1]
    if not all(np.isfinite(vals)):
        return False
    if x1 <= x0 or y1 <= y0:
        return False
    return True

def _clamp_int(v, lo, hi):
    return int(max(lo, min(hi, v)))

def _invert_monochrome1(arr: np.ndarray) -> np.ndarray:
    amax = float(np.nanmax(arr)) if np.isfinite(arr).any() else 0.0
    return (amax - arr).astype(arr.dtype, copy=False)

def _save_png16_linear(arr_float: np.ndarray, out_path: str, vmin: float, vmax: float):
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
        arr_u16 = np.zeros_like(arr_float, dtype=np.uint16)
    else:
        norm = (arr_float - vmin) / (vmax - vmin)
        arr_u16 = np.clip(norm * 65535.0, 0, 65535).astype(np.uint16)
    itk_im = itk.image_view_from_array(arr_u16)
    itk.imwrite(itk_im, out_path)

def _read_dicom_linear_itk(dcm_path: str):
    ds = pydicom.dcmread(dcm_path, force=True, stop_before_pixels=True)
    phot = str(getattr(ds, 'PhotometricInterpretation', 'MONOCHROME2')).upper()
    slope = float(getattr(ds, 'RescaleSlope', 1.0))
    intercept = float(getattr(ds, 'RescaleIntercept', 0.0))
    pixsp = getattr(ds, 'PixelSpacing', None)
    img = itk.imread(dcm_path, itk.F)
    arr = itk.GetArrayFromImage(img)
    if arr.ndim == 3:
        arr = arr[0]
    arr = arr.astype(np.float32, copy=False)
    inverted = False
    if 'MONOCHROME1' in phot:
        arr = _invert_monochrome1(arr)
        inverted = True
    spac = img.GetSpacing()
    if pixsp and len(pixsp) >= 2:
        try:
            pixsp_row = float(pixsp[0])
            pixsp_col = float(pixsp[1])
        except Exception:
            pixsp_row = float(spac[1])
            pixsp_col = float(spac[0])
    else:
        pixsp_row = float(spac[1])
        pixsp_col = float(spac[0])
    meta = dict(rows=int(arr.shape[0]), cols=int(arr.shape[1]), rescale_slope=slope, rescale_intercept=intercept, photometric=phot, inverted_to_mono2=inverted, pixel_spacing_row_mm=pixsp_row, pixel_spacing_col_mm=pixsp_col)
    return (arr, meta)

def _scale_box_to_dicom(csv_w, csv_h, dicom_w, dicom_h, xmin, ymin, xmax, ymax):
    if not all(np.isfinite([csv_w, csv_h])) or csv_w <= 0 or csv_h <= 0:
        sx = sy = 1.0
    else:
        sx = dicom_w / float(csv_w)
        sy = dicom_h / float(csv_h)
    x0 = int(math.floor(xmin * sx))
    y0 = int(math.floor(ymin * sy))
    x1 = int(math.ceil(xmax * sx))
    y1 = int(math.ceil(ymax * sy))
    x0 = _clamp_int(x0, 0, dicom_w - 1)
    x1 = _clamp_int(x1, 0, dicom_w)
    y0 = _clamp_int(y0, 0, dicom_h - 1)
    y1 = _clamp_int(y1, 0, dicom_h)
    if x1 <= x0:
        x1 = min(dicom_w, x0 + 1)
    if y1 <= y0:
        y1 = min(dicom_h, y0 + 1)
    return (x0, y0, x1, y1, sx, sy)

def main():
    df = pd.read_csv(INPUT_CSV)
    if 'full_image_path' not in df.columns:
        raise KeyError('Missing required column in CSV: full_image_path')
    has_w = 'width' in df.columns
    has_h = 'height' in df.columns
    for c in ('xmin', 'ymin', 'xmax', 'ymax'):
        if c not in df.columns:
            raise KeyError(f'Missing required box column in CSV: {c}')
    out_cols = ['lesion_image', 'lesion_npy', 'lesion_meta', 'roi_w_px', 'roi_h_px', 'pixsp_row_mm', 'pixsp_col_mm', 'used_box_source', 'gen_xmin', 'gen_ymin', 'gen_xmax', 'gen_ymax', '__stage1_error__']
    for c in out_cols:
        if c not in df.columns:
            df[c] = np.nan
    df[['lesion_image', 'lesion_npy', 'lesion_meta', 'used_box_source']] = df[['lesion_image', 'lesion_npy', 'lesion_meta', 'used_box_source']].astype(object)
    df['__stage1_error__'] = df['__stage1_error__'].astype(object)
    total = len(df)
    _log(f'[info] Rows to process: {total}')

    def out_paths(row_index, row):
        study = str(row.get('study_id', 'study'))
        imgid = str(row.get('image_id', 'img'))
        lat = str(row.get('laterality', 'X'))
        view = str(row.get('view_position', 'V'))
        sub = f'{study}_{lat}_{view}_{imgid}'
        base_dir = Path(ROI_ROOT) / sub
        base_dir.mkdir(parents=True, exist_ok=True)
        stem = f'lesion_{row_index:06d}'
        return (base_dir / (stem + PNG_SUFFIX), base_dir / (stem + '.npy'), base_dir / (stem + '.json'))
    processed_ok = 0
    skipped_no_box = 0
    errored = 0
    for i, row in df.iterrows():
        dcm_path = str(row['full_image_path']).strip()
        csv_xmin = _safe_float(row['xmin'])
        csv_ymin = _safe_float(row['ymin'])
        csv_xmax = _safe_float(row['xmax'])
        csv_ymax = _safe_float(row['ymax'])
        csv_w = _safe_float(row['width']) if has_w else np.nan
        csv_h = _safe_float(row['height']) if has_h else np.nan
        lesion_png = lesion_npy = lesion_meta = ''
        roi_w_px = roi_h_px = np.nan
        pixsp_row = pixsp_col = np.nan
        err = ''
        used_src = 'csv_box'
        gen_x0 = gen_y0 = gen_x1 = gen_y1 = np.nan
        try:
            if not _is_finite_box(csv_xmin, csv_ymin, csv_xmax, csv_ymax):
                used_src = 'none'
                err = 'skip:no_box'
                skipped_no_box += 1
                raise RuntimeError(err)
            if not dcm_path or not os.path.isfile(dcm_path):
                raise FileNotFoundError(f'DICOM not found: {dcm_path}')
            arr_lin, meta = _read_dicom_linear_itk(dcm_path)
            H, W = arr_lin.shape
            x0, y0, x1, y1, sx, sy = _scale_box_to_dicom(csv_w, csv_h, W, H, csv_xmin, csv_ymin, csv_xmax, csv_ymax)
            roi = arr_lin[y0:y1, x0:x1]
            roi_h, roi_w = roi.shape
            roi_w_px, roi_h_px = (int(roi_w), int(roi_h))
            gen_x0, gen_y0, gen_x1, gen_y1 = (float(x0), float(y0), float(x1), float(y1))
            png_path, npy_path, json_path = out_paths(i, row)
            if SAVE_PNG16:
                if np.isfinite(roi).any():
                    lin_min = float(np.nanmin(roi))
                    lin_max = float(np.nanmax(roi))
                else:
                    lin_min, lin_max = (0.0, 0.0)
                _save_png16_linear(roi, str(png_path), lin_min, lin_max)
                lesion_png = str(png_path)
            else:
                lin_min = lin_max = 0.0
            if SAVE_NPY:
                np.save(str(npy_path), roi.astype(np.float32))
                lesion_npy = str(npy_path)
            pixsp_row = float(meta['pixel_spacing_row_mm'])
            pixsp_col = float(meta['pixel_spacing_col_mm'])
            meta_out = dict(source_dicom=str(dcm_path), study_id=str(row.get('study_id', '')), image_id=str(row.get('image_id', '')), laterality=str(row.get('laterality', '')), view_position=str(row.get('view_position', '')), dicom_rows=int(meta['rows']), dicom_cols=int(meta['cols']), csv_width=float(csv_w) if np.isfinite(csv_w) else None, csv_height=float(csv_h) if np.isfinite(csv_h) else None, used_box_source=used_src, box_csv=dict(xmin=float(csv_xmin), ymin=float(csv_ymin), xmax=float(csv_xmax), ymax=float(csv_ymax)), box_dicom=dict(x0=int(x0), y0=int(y0), x1=int(x1), y1=int(y1)), scale_xy=dict(sx=float(sx), sy=float(sy)), pixel_spacing_row_mm=float(pixsp_row), pixel_spacing_col_mm=float(pixsp_col), photometric=str(meta['photometric']), inverted_to_mono2=bool(meta['inverted_to_mono2']), rescale_slope=float(meta['rescale_slope']), rescale_intercept=float(meta['rescale_intercept']), png_u16_linear_min=float(lin_min), png_u16_linear_max=float(lin_max), outputs=dict(lesion_image=str(png_path) if SAVE_PNG16 else None, lesion_npy=str(npy_path) if SAVE_NPY else None))
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(meta_out, f, indent=2)
            lesion_meta = str(json_path)
            processed_ok += 1
        except Exception as e:
            if not err:
                err = str(e)
            if 'skip:no_box' not in err:
                errored += 1
        df.at[i, 'lesion_image'] = lesion_png if lesion_png else np.nan
        df.at[i, 'lesion_npy'] = lesion_npy if lesion_npy else np.nan
        df.at[i, 'lesion_meta'] = lesion_meta if lesion_meta else np.nan
        df.at[i, 'roi_w_px'] = roi_w_px
        df.at[i, 'roi_h_px'] = roi_h_px
        df.at[i, 'pixsp_row_mm'] = pixsp_row
        df.at[i, 'pixsp_col_mm'] = pixsp_col
        df.at[i, 'used_box_source'] = used_src
        df.at[i, 'gen_xmin'] = gen_x0
        df.at[i, 'gen_ymin'] = gen_y0
        df.at[i, 'gen_xmax'] = gen_x1
        df.at[i, 'gen_ymax'] = gen_y1
        df.at[i, '__stage1_error__'] = np.nan if err == '' else err
        if VERBOSE and ((i + 1) % 50 == 0 or i + 1 == total):
            _log(f'[info] Processed {i + 1}/{total} (ok={processed_ok}, skipped_no_box={skipped_no_box}, errors={errored})')
    Path(os.path.dirname(OUTPUT_CSV) or '.').mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    _log(f'[done] OK: {processed_ok} | Skipped(no box): {skipped_no_box} | Errors: {errored} | Wrote: {OUTPUT_CSV}')

def run_lesion_stage1_safe(input_csv: str, output_csv: str, roi_root: str, save_png16: bool=True, save_npy: bool=True, verbose: bool=True, log_file: Optional[str]=None) -> str:
    if not isinstance(input_csv, str) or not input_csv:
        return '[error] input_csv must be a non-empty string'
    if not os.path.isfile(input_csv):
        return f'[error] input_csv does not exist: {input_csv}'
    if not isinstance(output_csv, str) or not output_csv:
        return '[error] output_csv must be a non-empty string'
    if not isinstance(roi_root, str) or not roi_root:
        return '[error] roi_root must be a non-empty string'
    try:
        df = pd.read_csv(input_csv, nrows=5)
    except Exception as e:
        return f'[error] failed to read CSV head: {e}'
    need = {'full_image_path', 'xmin', 'ymin', 'xmax', 'ymax'}
    missing = need - set(df.columns)
    if missing:
        return f'[error] missing required columns in CSV: {sorted(missing)}'
    set_input_csv(input_csv)
    set_output_csv(output_csv)
    set_roi_root(roi_root)
    set_save_flags(save_png16=save_png16, save_npy=save_npy, verbose=verbose)
    if log_file is None:
        log_file = os.path.join(roi_root, 'stage1.log')
    os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
    try:
        with open(log_file, 'w', encoding='utf-8') as fp:
            tee_out = _Tee(fp, sys.__stdout__)
            tee_err = _Tee(fp, sys.__stderr__)
            old_out, old_err = (sys.stdout, sys.stderr)
            sys.stdout, sys.stderr = (tee_out, tee_err)
            try:
                print(f'[info] Starting BOX-ONLY lesion extraction')
                print(f'[info] input_csv={INPUT_CSV}')
                print(f'[info] output_csv={OUTPUT_CSV}')
                print(f'[info] roi_root={ROI_ROOT}')
                print(f'[info] save_png16={SAVE_PNG16} save_npy={SAVE_NPY} verbose={VERBOSE}')
                main()
                print('[info] Stage1 finished.')
            except Exception as e:
                print(f'[error] Stage1 failed: {e}')
                return f'[error] Stage1 failed: {e}'
            finally:
                sys.stdout, sys.stderr = (old_out, old_err)
    except Exception as e:
        try:
            main()
            return f'[warn] Logging failed ({e}); stage1 finished without tee. Output CSV: {output_csv}'
        except Exception as e2:
            return f'[error] Stage1 failed (and logging failed): {e2}'
    return f'FINISHED: wrote {output_csv}. Log: {log_file}'
