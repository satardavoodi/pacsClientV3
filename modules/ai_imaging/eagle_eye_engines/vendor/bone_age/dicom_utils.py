# Imported inference implementation; provenance in ../provenance.json.
import os
import logging
from typing import List, Tuple
import numpy as np
import pydicom
from PIL import Image
log = logging.getLogger('BoneAgeAPI')
PLOW, PHIGH = (0.5, 99.5)

def is_dicom_file(path: str) -> bool:
    fl = path.lower()
    if fl.endswith(('.dcm', '.dicom', '.dicm')):
        return True
    return os.path.splitext(path)[1] == ''

def scan_dicoms(root: str) -> List[str]:
    if os.path.isfile(root):
        return [os.path.abspath(root)] if is_dicom_file(root) else []
    hits = []
    for r, _dirs, files in os.walk(root):
        for fn in files:
            if is_dicom_file(fn):
                hits.append(os.path.join(r, fn))
    hits.sort()
    return hits

def dicom_to_uint8(ds: 'pydicom.Dataset') -> np.ndarray:
    raw = ds.pixel_array
    arr = raw.astype(np.float32)
    slope = getattr(ds, 'RescaleSlope', None)
    intercept = getattr(ds, 'RescaleIntercept', None)
    if slope is not None and intercept is not None:
        arr = arr * float(slope) + float(intercept)
    photometric = str(getattr(ds, 'PhotometricInterpretation', '')).upper()
    wmin = float(np.percentile(arr, PLOW))
    wmax = float(np.percentile(arr, PHIGH))
    if wmax <= wmin:
        wmin, wmax = (float(arr.min()), float(arr.max()))
        if wmax <= wmin:
            wmax = wmin + 1.0
    arr = np.clip(arr, wmin, wmax)
    arr = (arr - wmin) / (wmax - wmin)
    if photometric == 'MONOCHROME1':
        arr = 1.0 - arr
    arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)
    span = int(arr.max()) - int(arr.min())
    if span < 150:
        log.warning(f'[dicom_utils] output dynamic range span={span}/255 is low; image contrast may be poor for this study.')
    dark_frac = float(np.mean(arr < 15))
    bright_frac = float(np.mean(arr > 240))
    bg_frac = dark_frac + bright_frac
    log.info(f'[dicom_utils][diag] shape={raw.shape} photometric={photometric} window=[{wmin:.1f},{wmax:.1f}] dark_frac={dark_frac:.2f} bright_frac={bright_frac:.2f} est_background_frac={bg_frac:.2f}')
    if bg_frac > 0.55:
        log.warning(f'[dicom_utils][diag] est_background_frac={bg_frac:.2f} is high - anatomy likely occupies a small portion of the frame; after letterbox resize the model may see a much smaller hand than in training data (possible cause of poor real-world accuracy).')
    return arr

def convert_dicom_file_to_png(dcm_path: str, out_dir: str, on_collision: str='rename') -> str:
    ds = pydicom.dcmread(dcm_path, force=True)
    img_u8 = dicom_to_uint8(ds)
    base = os.path.basename(dcm_path)
    stem, _ext = os.path.splitext(base)
    out_path = os.path.join(out_dir, stem + '.png')
    if os.path.exists(out_path):
        if on_collision == 'skip':
            return out_path
        if on_collision == 'rename':
            i = 1
            while os.path.exists(out_path):
                out_path = os.path.join(out_dir, f'{stem}_{i}.png')
                i += 1
    Image.fromarray(img_u8).save(out_path)
    return out_path

def convert_dicoms_to_png(dicom_paths: List[str], out_dir: str, on_collision: str='rename') -> Tuple[int, int, List[str]]:
    os.makedirs(out_dir, exist_ok=True)
    converted, failed = (0, 0)
    out_paths = []
    for dcm_path in dicom_paths:
        try:
            if not os.path.isfile(dcm_path):
                log.warning(f'[dicom_utils] file not found: {dcm_path}')
                failed += 1
                continue
            out_path = convert_dicom_file_to_png(dcm_path, out_dir, on_collision)
            out_paths.append(out_path)
            converted += 1
            log.info(f'[dicom_utils] converted {dcm_path} -> {out_path}')
        except Exception as e:
            failed += 1
            log.error(f'[dicom_utils] failed to convert {dcm_path}: {e}', exc_info=True)
    log.info(f'[dicom_utils] done: converted={converted} failed={failed}')
    return (converted, failed, out_paths)
