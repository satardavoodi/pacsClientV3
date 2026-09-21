# Imported inference implementation; provenance in ../provenance.json.
import os, sys, json, traceback, warnings
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from joblib import load
warnings.filterwarnings('ignore', category=UserWarning)
import os, sys, json, traceback, warnings
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from joblib import load
warnings.filterwarnings('ignore', category=UserWarning)

class PlattCalibrator:

    def __init__(self, *args, **kwargs):
        self.a_ = None
        self.b_ = None

    def transform(self, X):
        X = np.asarray(X, dtype=np.float64)
        if hasattr(self, 'a_') and hasattr(self, 'b_') and (self.a_ is not None):
            X = np.clip(X, 1e-15, 1 - 1e-15)
            logit = np.log(X / (1 - X))
            return 1.0 / (1.0 + np.exp(self.a_ * logit + self.b_))
        if hasattr(self, 'predict'):
            return self.predict(X)
        return X
if '__main__' in sys.modules:
    setattr(sys.modules['__main__'], 'PlattCalibrator', PlattCalibrator)
try:
    from resource_path import get_model_path
    MODEL_DIR = str(get_model_path(os.path.join('XGBoost_AR', 'models_stacked')))
except Exception:
    MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'XGBoost_AR', 'models_stacked')
FEATURES_CSV = os.path.join(MODEL_DIR, 'test_top4_multiview_features.csv')
OUT_CSV = os.path.join(MODEL_DIR, 'test_predictions_stacked.csv')
LABELS = ['No Finding', 'Mass', 'Suspicious Calcification', 'Focal Asymmetry']
KINDS = ['SINGLE', 'MV', 'BL', 'BOTH']
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
_GLOBAL_CACHE = {'used_kinds': None, 'stackers': None, 'calibrators': None, 'thresholds': None, 'base_models': {}, 'feature_lists': {}}
_CACHE_LOADED = False

def _load_models_to_cache(model_dir: str) -> None:
    global _GLOBAL_CACHE, _CACHE_LOADED
    if _CACHE_LOADED:
        _log('[cache] Models already loaded, skipping')
        return
    _log(f'[cache] Loading models into cache from: {model_dir}')
    try:
        _GLOBAL_CACHE['used_kinds'] = load(os.path.join(model_dir, 'stack_used_kinds.joblib'))
        _GLOBAL_CACHE['stackers'] = load(os.path.join(model_dir, 'stackers_per_label.joblib'))
        _GLOBAL_CACHE['calibrators'] = load(os.path.join(model_dir, 'calibrators_per_label.joblib'))
        _GLOBAL_CACHE['thresholds'] = np.load(os.path.join(model_dir, 'thresholds_STACKED.npy')).astype(np.float32)
        for k in KINDS:
            mdl_path = os.path.join(model_dir, f'xgb_ovr_{k}.joblib')
            if os.path.isfile(mdl_path):
                _GLOBAL_CACHE['base_models'][k] = load(mdl_path)
                _GLOBAL_CACHE['feature_lists'][k] = _load_feature_list(model_dir, k)
                _log(f'[cache] Loaded base models for KIND={k}')
        _CACHE_LOADED = True
        _log('[cache] All models cached successfully')
    except Exception as e:
        _log(f'[cache] Failed to load models: {e}')
        _CACHE_LOADED = False
        raise

def set_features_csv(path: str):
    global FEATURES_CSV
    FEATURES_CSV = str(path)

def set_model_dir(path: str):
    global MODEL_DIR
    MODEL_DIR = str(path)

def set_out_csv(path: str):
    global OUT_CSV
    OUT_CSV = str(path)

def set_verbose(flag: bool=True):
    global VERBOSE
    VERBOSE = bool(flag)

def get_expected_artifacts(model_dir: Optional[str]=None) -> Dict[str, str]:
    md = model_dir or MODEL_DIR
    return {'stack_used_kinds.joblib': os.path.join(md, 'stack_used_kinds.joblib'), 'stackers_per_label.joblib': os.path.join(md, 'stackers_per_label.joblib'), 'calibrators_per_label.joblib': os.path.join(md, 'calibrators_per_label.joblib'), 'thresholds_STACKED.npy': os.path.join(md, 'thresholds_STACKED.npy'), 'label_order.txt': os.path.join(md, 'label_order.txt'), **{f'xgb_ovr_{k}.joblib': os.path.join(md, f'xgb_ovr_{k}.joblib') for k in KINDS}, **{f'feature_list_{k}.txt': os.path.join(md, f'feature_list_{k}.txt') for k in KINDS}}

def _load_feature_list(md: str, name: str) -> Optional[List[str]]:
    path = os.path.join(md, f'feature_list_{name}.txt')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            cols = [l.strip() for l in f if l.strip()]
        if not cols:
            _log(f'[warn] empty feature list for KIND={name}: {path}')
        return cols
    except Exception as e:
        _log(f'[warn] cannot load feature list for KIND={name}: {e}')
        return None

def _build_X(df: pd.DataFrame, cols: List[str]) -> np.ndarray:
    try:
        X = df.reindex(columns=cols, fill_value=np.nan).copy()
        b = X.select_dtypes(include=['bool']).columns
        if len(b):
            X[b] = X[b].astype(np.float32)
        return X.astype('float32').replace([np.inf, -np.inf], np.nan).values
    except Exception as e:
        raise RuntimeError(f'failed to build X for cols (n={len(cols)}): {e}')

def _predict_kind(models: List, X: np.ndarray) -> np.ndarray:
    try:
        probs = []
        for i, m in enumerate(models):
            if m is None:
                _log(f'[warn] model[{i}] is None; filling with NaNs')
                probs.append(np.full((X.shape[0],), np.nan, dtype=np.float32))
            elif isinstance(m, (list, tuple)):
                sub_preds = []
                for j, sub_m in enumerate(m):
                    if sub_m is None:
                        continue
                    try:
                        sub_preds.append(sub_m.predict_proba(X)[:, 1])
                    except Exception as sub_e:
                        _log(f'[warn] model[{i}][{j}] predict_proba failed: {sub_e}')
                if not sub_preds:
                    _log(f'[warn] model[{i}] all sub-models failed/empty; filling with NaNs')
                    probs.append(np.full((X.shape[0],), np.nan, dtype=np.float32))
                else:
                    p = np.mean(np.column_stack(sub_preds), axis=1)
                    probs.append(p.astype(np.float32, copy=False))
            else:
                p = m.predict_proba(X)[:, 1]
                probs.append(p.astype(np.float32, copy=False))
        return np.column_stack(probs).astype(np.float32, copy=False)
    except Exception as e:
        raise RuntimeError(f'kind prediction failed: {e}')

def main():
    if not os.path.isfile(FEATURES_CSV):
        raise FileNotFoundError(f'FEATURES_CSV not found: {FEATURES_CSV}')
    _log(f'[info] Loading features: {FEATURES_CSV}')
    df = pd.read_csv(FEATURES_CSV, low_memory=False)
    N = len(df)
    C = len(LABELS)
    _log(f'[info] Rows={N} | Columns={len(df.columns)}')
    _log('[info] Loading stack artifacts...')
    _load_models_to_cache(MODEL_DIR)
    used_kinds = _GLOBAL_CACHE['used_kinds']
    stackers = _GLOBAL_CACHE['stackers']
    calibrators = _GLOBAL_CACHE['calibrators']
    thresholds = _GLOBAL_CACHE['thresholds']
    if not isinstance(used_kinds, (list, tuple)) or not used_kinds:
        raise RuntimeError('used_kinds is empty or invalid.')
    for lbl in LABELS:
        if lbl not in stackers:
            raise RuntimeError(f'stacker missing for label: {lbl}')
        if lbl not in calibrators:
            _log(f'[warn] calibrator missing for label: {lbl} (will proceed without)')
    _log(f'[info] used_kinds = {list(used_kinds)}')
    _log(f'[info] thresholds: NF(–), Mass={thresholds[1]:.3f}, Calc={thresholds[2]:.3f}, FA={thresholds[3]:.3f}')
    P_by_kind = {}
    for k in used_kinds:
        if k not in _GLOBAL_CACHE['base_models']:
            _log(f'[warn] skipping KIND={k}: not in cache')
            continue
        try:
            models = _GLOBAL_CACHE['base_models'][k]
            feats = _GLOBAL_CACHE['feature_lists'][k]
            if not feats:
                _log(f'[warn] skipping KIND={k}: empty or missing feature list.')
                continue
            X = _build_X(df, feats)
            P_by_kind[k] = _predict_kind(models, X)
            _log(f'[ok] KIND={k}: predicted base probabilities.')
        except Exception as e:
            _log(f'[warn] KIND={k} failed: {e}')
            _log(traceback.format_exc())
    if not P_by_kind:
        raise RuntimeError('No base predictions available (all KINDs failed or missing).')
    P_final = np.zeros((N, C), dtype=np.float32)
    for c, lbl in enumerate(LABELS):
        try:
            cols = []
            for k in KINDS:
                if k in P_by_kind:
                    cols.append(P_by_kind[k][:, c])
            Xc = np.column_stack(cols) if cols else np.zeros((N, 0), dtype=np.float32)
            stk = stackers[lbl]
            if Xc.shape[1] == 0:
                _log(f'[warn] no stack inputs for label={lbl}; using zeros')
                Pc = np.zeros((N,), dtype=np.float32)
            else:
                Pc = stk.predict_proba(Xc)[:, 1].astype(np.float32, copy=False)
            cal = calibrators.get(lbl, None)
            if cal is not None:
                try:
                    Pc = cal.transform(Pc).astype(np.float32, copy=False)
                except Exception as e:
                    _log(f'[warn] calibrator transform failed for {lbl}: {e}')
            P_final[:, c] = Pc
        except Exception as e:
            _log(f'[warn] stacking failed for label={lbl}: {e}')
            _log(traceback.format_exc())
            P_final[:, c] = np.full((N,), np.nan, dtype=np.float32)
    Yhat = np.zeros((N, C), dtype=int)
    Yhat[:, 1] = (P_final[:, 1] >= thresholds[1]).astype(int)
    Yhat[:, 2] = (P_final[:, 2] >= thresholds[2]).astype(int)
    Yhat[:, 3] = (P_final[:, 3] >= thresholds[3]).astype(int)
    none = Yhat[:, 1:].sum(axis=1) == 0
    Yhat[none, 0] = 1
    Yhat[Yhat[:, 1:].any(axis=1), 0] = 0
    _log('[info] Writing predictions CSV...')
    out = pd.DataFrame({'row_index': np.arange(N, dtype=np.int64), 'model_kind': 'STACKED_v52'})
    ID_CANDIDATES = ['study_instance_uid', 'series_instance_uid', 'patient_id', 'study_id', 'laterality', 'view_position', 'full_image_path', 'dicom_full_path', 'lesion_image', 'xmin', 'ymin', 'xmax', 'ymax', 'gen_xmin', 'gen_ymin', 'gen_xmax', 'gen_ymax']
    for col in ID_CANDIDATES:
        if col in df.columns:
            out[col] = df[col]
    for i, lbl in enumerate(LABELS):
        out[f'prob_{lbl}'] = P_final[:, i]
        out[f'pred_{lbl}'] = Yhat[:, i].astype(int)
    out['labels_pred'] = [str([LABELS[i] for i in range(C) if Yhat[r, i] == 1]) for r in range(N)]
    if not all((c in out.columns for c in ['xmin', 'ymin', 'xmax', 'ymax'])):
        if all((c in out.columns for c in ['gen_xmin', 'gen_ymin', 'gen_xmax', 'gen_ymax'])):
            out['xmin'] = out['gen_xmin']
            out['ymin'] = out['gen_ymin']
            out['xmax'] = out['gen_xmax']
            out['ymax'] = out['gen_ymax']
    if 'full_image_path' not in out.columns and 'dicom_full_path' in out.columns:
        out['full_image_path'] = out['dicom_full_path']
    FIRST_IDS = [c for c in ['row_index', 'study_instance_uid', 'series_instance_uid', 'patient_id', 'study_id', 'laterality', 'view_position', 'full_image_path', 'lesion_image'] if c in out.columns]
    FIRST_BOX = [c for c in ['xmin', 'ymin', 'xmax', 'ymax'] if c in out.columns]
    first = FIRST_IDS + FIRST_BOX
    rest = [c for c in out.columns if c not in first]
    out = out[first + rest]
    os.makedirs(os.path.dirname(OUT_CSV) or '.', exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    _log(f'[ok] Saved predictions → {OUT_CSV}')

def preload_models(model_dir: Optional[str]=None):
    md = model_dir or MODEL_DIR
    _log(f'[preload] Starting XGBoost model preload from: {md}')
    set_model_dir(md)
    _load_models_to_cache(md)
    _log('[preload] XGBoost models preloaded successfully')

def run_stacked_infer_safe(features_csv: str, model_dir: str, out_csv: Optional[str]=None, verbose: bool=True, log_file: Optional[str]=None) -> str:
    if not isinstance(features_csv, str) or not features_csv:
        return '[error] features_csv must be a non-empty string'
    if not os.path.isfile(features_csv):
        return f'[error] features_csv does not exist: {features_csv}'
    if not isinstance(model_dir, str) or not model_dir:
        return '[error] model_dir must be a non-empty string'
    if not os.path.isdir(model_dir):
        return f'[error] model_dir does not exist: {model_dir}'
    if out_csv is None:
        out_csv = os.path.join(model_dir, 'predictions_stacked.csv')
    if log_file is None:
        log_file = os.path.join(model_dir, 'inference_stacked.log')
    set_features_csv(features_csv)
    set_model_dir(model_dir)
    set_out_csv(out_csv)
    set_verbose(bool(verbose))
    try:
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        with open(log_file, 'w', encoding='utf-8') as fp:
            tee_out = _Tee(fp, sys.__stdout__)
            tee_err = _Tee(fp, sys.__stderr__)
            old_out, old_err = (sys.stdout, sys.stderr)
            sys.stdout, sys.stderr = (tee_out, tee_err)
            try:
                print(f'[info] Starting STACKED inference')
                print(f'[info] features_csv={FEATURES_CSV}')
                print(f'[info] model_dir={MODEL_DIR}')
                print(f'[info] out_csv={OUT_CSV}')
                print(f'[info] verbose={VERBOSE}')
                main()
                print('[info] Inference finished.')
            except Exception as e:
                traceback.print_exc()
                return f'[error] inference failed: {e}'
            finally:
                sys.stdout, sys.stderr = (old_out, old_err)
    except Exception as e:
        try:
            main()
            return f'[warn] logging failed ({e}); inference finished without tee. Output: {out_csv}'
        except Exception as e2:
            return f'[error] inference failed (and logging failed): {e2}'
    return f'FINISHED: wrote {out_csv}. Log: {log_file}'
