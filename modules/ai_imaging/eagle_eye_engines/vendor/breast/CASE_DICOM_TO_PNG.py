# Imported inference implementation; provenance in ../provenance.json.
import os, sys, traceback
from collections import Counter
from typing import List, Tuple, Optional
import numpy as np
import itk
import pydicom
from pydicom.pixel_data_handlers.util import apply_modality_lut, apply_voi_lut
import imageio.v3 as iio
INPUT_ROOT = ''
OUTPUT_DIR = ''
ON_COLLISION = 'rename'
LOG_EVERY = 100
EXTRACT_FROM_MULTIFRAME = True
FRAME_INDEX = 0
VERBOSE = True

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

def _log(msg: str):
    if VERBOSE:
        print(msg)

def set_input_root(path: str):
    global INPUT_ROOT
    INPUT_ROOT = str(path)

def set_output_dir(path: str):
    global OUTPUT_DIR
    OUTPUT_DIR = str(path)

def set_on_collision(mode: str):
    global ON_COLLISION
    ON_COLLISION = str(mode)

def set_extract_from_multiframe(flag: bool, frame_index: int=0):
    global EXTRACT_FROM_MULTIFRAME, FRAME_INDEX
    EXTRACT_FROM_MULTIFRAME = bool(flag)
    FRAME_INDEX = int(frame_index)

def set_verbose(flag: bool=True):
    global VERBOSE
    VERBOSE = bool(flag)

def get_config() -> dict:
    return {'INPUT_ROOT': INPUT_ROOT, 'OUTPUT_DIR': OUTPUT_DIR, 'ON_COLLISION': ON_COLLISION, 'LOG_EVERY': LOG_EVERY, 'EXTRACT_FROM_MULTIFRAME': EXTRACT_FROM_MULTIFRAME, 'FRAME_INDEX': FRAME_INDEX, 'VERBOSE': VERBOSE}

def ensure_dir(path: str):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        raise RuntimeError(f'cannot create output directory: {path} ({e})')

def is_dicom_file(fname: str) -> bool:
    try:
        return fname.lower().endswith(('.dcm', '.dicom', '.dicm'))
    except Exception:
        return False

def scan_dicoms(root: str) -> List[str]:
    hits = []
    try:
        if os.path.isfile(root):
            if is_dicom_file(root):
                hits.append(os.path.abspath(root))
            return hits
        for r, _dirs, files in os.walk(root):
            for fn in files:
                if is_dicom_file(fn):
                    hits.append(os.path.join(r, fn))
        hits.sort()
        return hits
    except Exception as e:
        raise RuntimeError(f'failed to scan dicoms under {root}: {e}')

def make_png_name(dicom_path: str) -> str:
    base = os.path.basename(dicom_path)
    bl = base.lower()
    for ext in ('.dcm', '.dicom', '.dicm'):
        if bl.endswith(ext):
            base = base[:-len(ext)]
            break
    return base + '.png'

def unique_outpath(out_dir: str, png_name: str, collision_mode: str) -> Tuple[str, bool]:
    out_path = os.path.abspath(os.path.join(out_dir, png_name))
    if not os.path.exists(out_path):
        return (out_path, True)
    if collision_mode == 'overwrite':
        return (out_path, True)
    if collision_mode == 'skip':
        return (out_path, False)
    stem, ext = os.path.splitext(out_path)
    i = 1
    while os.path.exists(f'{stem}_{i}{ext}'):
        i += 1
    return (f'{stem}_{i}{ext}', True)

def _parse_first_float(val: Optional[str]) -> Optional[float]:
    if val is None:
        return None
    try:
        s = str(val).strip()
        for sep in ('\\', '/', ' '):
            if sep in s:
                s = s.split(sep)[0].strip()
                break
        return float(s)
    except Exception:
        return None

def _to_float(img):
    dim = img.GetImageDimension()
    return itk.cast_image_filter(img, ttype=(type(img), itk.Image[itk.F, dim]))

def _window_or_rescale_to_u8(img2d, mdict: dict):
    wc = _parse_first_float(mdict.get('0028|1050'))
    ww = _parse_first_float(mdict.get('0028|1051'))
    photometric = (mdict.get('0028|0004') or '').upper()
    if 'RGB' in photometric:
        try:
            img2d = itk.vector_index_selection_cast_image_filter(img2d, index=0, ttype=(type(img2d), itk.Image[itk.template(img2d)[1][0], 2]))
        except Exception:
            pass
    if wc is not None and ww is not None and (ww > 0.0):
        imgf = _to_float(img2d)
        wmin = wc - ww / 2.0
        wmax = wc + ww / 2.0
        win = itk.intensity_windowing_image_filter(imgf, window_minimum=wmin, window_maximum=wmax, output_minimum=0.0, output_maximum=255.0)
        out = itk.cast_image_filter(win, ttype=(type(win), itk.Image[itk.UC, 2]))
    else:
        rng = itk.rescale_intensity_image_filter(img2d, output_minimum=0, output_maximum=255)
        out = itk.cast_image_filter(rng, ttype=(type(rng), itk.Image[itk.UC, 2]))
    if photometric.startswith('MONOCHROME1'):
        out = itk.shift_scale_image_filter(out, shift=255.0, scale=-1.0)
    return out

def _extract_frame_2d_from_3d(img3d, frame_index: int):
    arr = itk.GetArrayViewFromImage(img3d)
    if arr.ndim != 3 or arr.shape[0] == 0:
        raise RuntimeError('unexpected 3D array shape for multi-frame image.')
    k = max(0, min(int(frame_index), arr.shape[0] - 1))
    slice2d = np.asarray(arr[k, :, :])
    out2d = itk.GetImageFromArray(slice2d)
    return out2d

def _read_dicom_u8_with_pydicom(dcm_path: str, frame_index: int) -> np.ndarray:
    ds = pydicom.dcmread(dcm_path, force=True, stop_before_pixels=False)
    arr = ds.pixel_array
    if arr.ndim == 3:
        k = max(0, min(int(frame_index), arr.shape[0] - 1))
        arr = arr[k]
    try:
        arr = apply_modality_lut(arr, ds)
    except Exception:
        pass
    try:
        arr = apply_voi_lut(arr, ds)
    except Exception:
        pass
    photometric = (getattr(ds, 'PhotometricInterpretation', '') or '').upper()
    if photometric.startswith('MONOCHROME1'):
        mx = float(np.max(arr)) if np.max(arr) > 0 else 1.0
        arr = mx - arr
    arr = arr.astype(np.float32)
    mn, mx = (float(np.min(arr)), float(np.max(arr)))
    if mx <= mn:
        return np.zeros_like(arr, dtype=np.uint8)
    return ((arr - mn) / (mx - mn) * 255.0).clip(0, 255).astype(np.uint8)

def _save_png_numpy_u8(out_path: str, arr_u8: np.ndarray):
    iio.imwrite(out_path, arr_u8)

def convert_one(dcm_path: str) -> Tuple[bool, str]:
    try:
        png_name = make_png_name(dcm_path)
        out_path, should_write = unique_outpath(OUTPUT_DIR, png_name, ON_COLLISION)
        if not should_write:
            return (False, 'exists_skipped')
        arr_u8 = _read_dicom_u8_with_pydicom(dcm_path, FRAME_INDEX)
        _save_png_numpy_u8(out_path, arr_u8)
        return (True, out_path)
    except Exception as e:
        return (False, f'read_or_write_fail: {e}')

def main():
    if not isinstance(INPUT_ROOT, str) or not INPUT_ROOT:
        raise ValueError('INPUT_ROOT must be a non-empty string.')
    if not (os.path.isdir(INPUT_ROOT) or os.path.isfile(INPUT_ROOT)):
        raise FileNotFoundError(f'INPUT_ROOT does not exist: {INPUT_ROOT}')
    if not isinstance(OUTPUT_DIR, str) or not OUTPUT_DIR:
        raise ValueError('OUTPUT_DIR must be a non-empty string.')
    ensure_dir(OUTPUT_DIR)
    if ON_COLLISION not in {'rename', 'skip', 'overwrite'}:
        raise ValueError("ON_COLLISION must be one of: 'rename', 'skip', 'overwrite'.")
    if not isinstance(EXTRACT_FROM_MULTIFRAME, bool):
        raise ValueError('EXTRACT_FROM_MULTIFRAME must be bool.')
    if int(FRAME_INDEX) < 0:
        raise ValueError('FRAME_INDEX must be >= 0.')
    files = scan_dicoms(INPUT_ROOT)
    if not files:
        print(f'No DICOM files found under: {INPUT_ROOT}')
        return
    print(f'Found {len(files)} DICOM file(s).')
    print(f'Output → {OUTPUT_DIR}')
    print(f'Collision policy: {ON_COLLISION}')
    if EXTRACT_FROM_MULTIFRAME:
        print(f'Multi-frame: extracting slice index {FRAME_INDEX}')
    written = 0
    reasons = Counter()
    for i, fp in enumerate(files, 1):
        ok, info = convert_one(fp)
        if ok:
            written += 1
            _log(f'[ok] {fp} → {info}')
        else:
            reasons[info] += 1
            _log(f'[skip] {fp} → {info}')
        if i % max(1, LOG_EVERY) == 0:
            print(f'[{i}/{len(files)}] written={written}, skipped={sum(reasons.values())}')
    print('\n=== Done ===')
    print(f'Total DICOMs : {len(files)}')
    print(f'PNGs written : {written}')
    print('Skips / Failures by reason:')
    for r, c in reasons.most_common():
        print(f'  - {r:>20}: {c}')
    print(f'Output directory      : {OUTPUT_DIR}')

def run_dicom2png_safe(input_root: str, output_dir: str, on_collision: str='rename', extract_from_multiframe: bool=True, frame_index: int=0, log_every: int=100, verbose: bool=True, log_file: Optional[str]=None) -> str:
    if not isinstance(input_root, str) or not input_root:
        return '[error] input_root must be a non-empty string'
    if not (os.path.isdir(input_root) or os.path.isfile(input_root)):
        return f'[error] input_root does not exist: {input_root}'
    if not isinstance(output_dir, str) or not output_dir:
        return '[error] output_dir must be a non-empty string'
    if on_collision not in {'rename', 'skip', 'overwrite'}:
        return '[error] on_collision must be one of: rename | skip | overwrite'
    if int(frame_index) < 0:
        return '[error] frame_index must be >= 0'
    if int(log_every) <= 0:
        return '[error] log_every must be > 0'
    try:
        ensure_dir(output_dir)
    except Exception as e:
        return f'[error] cannot create output_dir: {e}'
    global INPUT_ROOT, OUTPUT_DIR, ON_COLLISION, EXTRACT_FROM_MULTIFRAME, FRAME_INDEX, LOG_EVERY, VERBOSE
    INPUT_ROOT = input_root
    OUTPUT_DIR = output_dir
    ON_COLLISION = on_collision
    EXTRACT_FROM_MULTIFRAME = bool(extract_from_multiframe)
    FRAME_INDEX = int(frame_index)
    LOG_EVERY = int(log_every)
    VERBOSE = bool(verbose)
    if log_file is None:
        log_file = os.path.join(OUTPUT_DIR, 'dicom2png.log')
    try:
        with open(log_file, 'w', encoding='utf-8') as fp:
            tee_out = _Tee(fp, sys.__stdout__)
            tee_err = _Tee(fp, sys.__stderr__)
            old_out, old_err = (sys.stdout, sys.stderr)
            sys.stdout, sys.stderr = (tee_out, tee_err)
            try:
                print('[info] Starting DICOM→PNG conversion')
                print('[info] Config:', get_config())
                main()
                print('[info] Conversion finished.')
            except Exception as e:
                traceback.print_exc()
                return f'[error] conversion failed: {e}'
            finally:
                sys.stdout, sys.stderr = (old_out, old_err)
    except Exception as e:
        try:
            main()
            return f'[warn] logging failed ({e}); conversion finished without tee. Output: {OUTPUT_DIR}'
        except Exception as e2:
            return f'[error] conversion failed (and logging failed): {e2}'
    return f'FINISHED: wrote PNGs to {OUTPUT_DIR}. Log: {log_file}'
