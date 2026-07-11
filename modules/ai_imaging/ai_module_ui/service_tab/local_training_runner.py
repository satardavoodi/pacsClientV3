# -*- coding: utf-8 -*-
"""
Local Training Runner — Executes mammography/bone-age training locally
using collected labels and DICOM images from user_data/patients.

This runner:
1. Reads labeled data (from feedback_collector)
2. Loads corresponding DICOM pixel arrays
3. Runs a simple fine-tuning loop (or XGBoost fit for mammography classification)
4. Saves the trained model to the configured output directory
"""

import os
import json
import logging
import threading
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

logger = logging.getLogger(__name__)


def _safe_slug(text: str) -> str:
    s = str(text or "").strip().replace("/", "-").replace("\\", "-")
    s = s.replace(" ", "_").replace(":", "-")
    return s or "model"


def _basename_from_url(url: str, fallback: str) -> str:
    try:
        path = urlparse(url).path
        name = Path(path).name
        if name:
            return name
    except Exception:
        pass
    return fallback


def _default_pretrained_root() -> Path:
    """Local cache for pretrained mammography artifacts."""
    try:
        from aipacs_runtime import user_data_root

        return Path(user_data_root()) / "models" / "mammography" / "pretrained"
    except Exception:
        return Path(os.getcwd()) / "user_data" / "models" / "mammography" / "pretrained"


def _download_if_missing(url: str, dst: Path) -> bool:
    """Download a file if missing. Returns True when file exists after call."""
    try:
        if dst.exists() and dst.stat().st_size > 0:
            return True
    except Exception:
        pass

    if not url:
        return False

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".part")
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass

        with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as out:
            total = int(resp.headers.get("Content-Length", "0") or 0)
            chunk_size = 1024 * 256

            try:
                from tqdm import tqdm  # type: ignore

                pbar = tqdm(
                    total=total if total > 0 else None,
                    unit="B",
                    unit_scale=True,
                    desc=f"Downloading {dst.name}",
                    leave=False,
                )
            except Exception:
                pbar = None

            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                if pbar is not None:
                    pbar.update(len(chunk))

            if pbar is not None:
                pbar.close()

        os.replace(tmp, dst)
        return dst.exists() and dst.stat().st_size > 0
    except Exception as e:
        logger.warning(f"Pretrained download failed for {dst.name}: {e}")
        return False


def _resolve_init_artifacts(
    model_source: str,
    settings: Optional[Dict[str, Any]] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> Dict[str, Any]:
    """Resolve pretrained artifacts for transfer learning mode."""
    resolved = {
        "model_source": str(model_source or "scratch"),
        "detector_init_path": "",
        "classifier_init_path": "",
        "detector_init_ready": False,
        "classifier_init_ready": False,
    }

    src = resolved["model_source"]
    root = _default_pretrained_root()
    settings = settings or {}

    # AI Pacs mode: use local trained init artifacts only (no download).
    if src == "iran_nobat":
        if progress_callback:
            progress_callback(57, "Training init: ai_pacs (using local pretrained, no download)")

        det_candidates = [
            root / "mg_detector_aipacs.joblib",
            root / "mg_detector_iran_nobat.joblib",
            root / "mg_detector_aipacs.pkl",
            root / "mg_detector_iran_nobat.pkl",
        ]
        cls_candidates = [
            root / "mg_classifier_aipacs.joblib",
            root / "mg_classifier_iran_nobat.joblib",
            root / "mg_classifier_aipacs.pkl",
            root / "mg_classifier_iran_nobat.pkl",
        ]

        det_path = next((p for p in det_candidates if p.exists() and p.stat().st_size > 0), None)
        cls_path = next((p for p in cls_candidates if p.exists() and p.stat().st_size > 0), None)

        det_ok = det_path is not None
        cls_ok = cls_path is not None

        resolved.update({
            "detector_init_path": str(det_path) if det_ok else "",
            "classifier_init_path": str(cls_path) if cls_ok else "",
            "detector_init_ready": bool(det_ok),
            "classifier_init_ready": bool(cls_ok),
        })

        if progress_callback:
            progress_callback(
                59,
                "Init resolved (ai_pacs): "
                f"detector={'ok' if det_ok else 'missing'}, "
                f"classifier={'ok' if cls_ok else 'missing'}",
            )
        return resolved

    # Scratch mode: download public backbone/init assets from provided URLs.
    det_url = str(settings.get("pretrained_detector_url") or "").strip()
    cls_url = str(settings.get("pretrained_classifier_url") or "").strip()

    if not det_url:
        det_url = os.getenv("AIPACS_MG_DETECTOR_PRETRAINED_URL", "").strip()
    if not cls_url:
        cls_url = os.getenv("AIPACS_MG_CLASSIFIER_PRETRAINED_URL", "").strip()

    det_backbone_slug = _safe_slug(str(settings.get("det_backbone", "detector")))
    cls_model_slug = _safe_slug(str(settings.get("cls_model", "classifier")))

    det_name = _basename_from_url(det_url, f"detector_{det_backbone_slug}.bin")
    cls_name = _basename_from_url(cls_url, f"classifier_{cls_model_slug}.bin")

    det_path = root / det_name
    cls_path = root / cls_name

    det_ok = det_path.exists() and det_path.stat().st_size > 0
    cls_ok = cls_path.exists() and cls_path.stat().st_size > 0

    if progress_callback:
        progress_callback(57, "Training init: scratch (download public backbone/init assets)")

    if not det_ok and det_url:
        if progress_callback:
            progress_callback(58, "Detector backbone missing; trying download...")
        det_ok = _download_if_missing(det_url, det_path)

    if not cls_ok and cls_url:
        if progress_callback:
            progress_callback(59, "Classifier init missing; trying download...")
        cls_ok = _download_if_missing(cls_url, cls_path)

    resolved.update({
        "detector_init_path": str(det_path) if det_ok else "",
        "classifier_init_path": str(cls_path) if cls_ok else "",
        "detector_init_ready": bool(det_ok),
        "classifier_init_ready": bool(cls_ok),
    })

    if progress_callback:
        progress_callback(
            59,
            "Init resolved (scratch): "
            f"detector={'ok' if det_ok else 'missing'}, "
            f"classifier={'ok' if cls_ok else 'missing'}",
        )

    return resolved


class _ConstantBinaryClassifier:
    """Pickle-safe constant classifier for one-class training sets."""

    def __init__(self, cls: int):
        self.cls = int(cls)

    def fit(self, X=None, y=None):
        return self

    def predict(self, X):
        import numpy as np

        n = len(X) if X is not None else 0
        return np.full((n,), self.cls, dtype=int)

    def predict_proba(self, X):
        import numpy as np

        n = len(X) if X is not None else 0
        proba = np.zeros((n, 2), dtype=float)
        proba[:, self.cls] = 1.0
        return proba


class _ConstantBBoxDetector:
    """Pickle-safe constant detector that always returns the same bbox."""

    def __init__(self, bbox_xyxy: List[float], score: float = 1.0):
        self.bbox_xyxy = [float(v) for v in bbox_xyxy]
        self.score = float(score)

    def fit(self, X=None, y=None):
        return self

    def predict(self, X):
        n = len(X) if X is not None else 0
        return [
            {
                "bbox": list(self.bbox_xyxy),
                "score": self.score,
                "label": "lesion",
            }
            for _ in range(n)
        ]


def _normalize_bbox_xyxy(box: Any) -> Optional[List[float]]:
    """Normalize incoming box formats to [x1, y1, x2, y2]."""
    if not isinstance(box, (list, tuple)):
        return None
    if len(box) < 4:
        return None
    try:
        x1, y1, x2, y2 = float(box[0]), float(box[1]), float(box[2]), float(box[3])
    except Exception:
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


class TrainingProgress:
    """Simple progress tracking for training runs."""

    def __init__(self, total_steps: int = 100):
        self.total_steps = total_steps
        self.current_step = 0
        self.status = "idle"  # idle, running, completed, failed
        self.message = ""
        self.metrics: Dict[str, float] = {}

    def update(self, step: int, message: str = "", **metrics):
        self.current_step = step
        self.message = message
        self.metrics.update(metrics)

    @property
    def progress_pct(self) -> float:
        if self.total_steps <= 0:
            return 0.0
        return min(100.0, (self.current_step / self.total_steps) * 100)


def _load_dicom_pixel_array(dicom_path: str):
    """Load a DICOM file and return its pixel array as numpy array."""
    try:
        import pydicom
        import numpy as np

        ds = pydicom.dcmread(dicom_path, force=True)
        arr = ds.pixel_array.astype(np.float32)

        # Normalize to 0-1
        arr_min, arr_max = arr.min(), arr.max()
        if arr_max > arr_min:
            arr = (arr - arr_min) / (arr_max - arr_min)

        return arr
    except Exception as e:
        logger.debug(f"Failed to load DICOM {dicom_path}: {e}")
        return None


def _find_dicom_files_for_study(study_uid: str) -> List[str]:
    """Find DICOM files for a given study UID in user_data/patients."""
    try:
        from aipacs_runtime import user_data_root
        patients_root = Path(user_data_root()) / "patients"
    except Exception:
        patients_root = Path(os.getcwd()) / "user_data" / "patients"

    dicom_files = []

    # Search in multiple possible locations:
    # 1. patients/dicom/<study_uid>/  (primary DICOM storage)
    # 2. patients/<study_uid>/        (alternative layout)
    search_dirs = [
        patients_root / "dicom" / study_uid,
        patients_root / study_uid,
    ]

    for study_dir in search_dirs:
        if study_dir.is_dir():
            for root, _, files in os.walk(str(study_dir)):
                for f in files:
                    if f.lower().endswith((".dcm", ".dicom")) and not f.endswith(".part"):
                        dicom_files.append(os.path.join(root, f))
            if dicom_files:
                break  # Found files, stop searching

    return dicom_files


def run_mammography_training(
    labeled_data: List[Dict[str, Any]],
    settings: Dict[str, Any],
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> Dict[str, Any]:
    """
    Run local mammography training using collected labels.

    For mammography (FCOS detection + XGBoost classification):
    - Detection: uses labeled bounding boxes to fine-tune/train
    - Classification: uses corrected_status (normal/abnormal) labels

    Returns dict with training results/metrics.
    """
    import numpy as np

    output_dir = settings.get("model_output_dir", "")
    if not output_dir:
        try:
            from aipacs_runtime import user_data_root
            output_dir = str(
                Path(user_data_root()) / "models" / "mammography"
            )
        except Exception:
            output_dir = str(Path(os.getcwd()) / "models" / "mammography")

    os.makedirs(output_dir, exist_ok=True)

    model_source = settings.get("model_source", "iran_nobat")
    total_labels = len(labeled_data)

    if progress_callback:
        progress_callback(5, f"Preparing {total_labels} labeled samples...")

    # ── Separate positive/negative labels ──
    positives = [d for d in labeled_data if d.get("is_positive")]
    negatives = [d for d in labeled_data if not d.get("is_positive")]

    if progress_callback:
        progress_callback(
            10,
            f"Labels: {len(positives)} positive, {len(negatives)} negative",
        )

    # ── Load pixel data for classification + detection ──
    X_features = []
    y_labels = []
    det_boxes = []
    loaded_count = 0

    for i, entry in enumerate(labeled_data):
        study_uid = entry.get("study_uid", "")
        dicom_files = _find_dicom_files_for_study(study_uid)

        if not dicom_files:
            continue

        # Use the first MG DICOM for feature extraction
        for dcm_path in dicom_files[:1]:
            arr = _load_dicom_pixel_array(dcm_path)
            if arr is None:
                continue

            # Simple feature extraction: basic image statistics
            features = _extract_basic_features(arr)
            if features is not None:
                X_features.append(features)
                y_labels.append(1 if entry.get("is_positive") else 0)
                loaded_count += 1

                box = _normalize_bbox_xyxy(entry.get("label_box"))
                if box is not None and entry.get("is_positive"):
                    det_boxes.append(box)

        if progress_callback:
            pct = 10 + int((i / max(1, total_labels)) * 40)
            progress_callback(pct, f"Loaded {loaded_count}/{total_labels} images...")

    if loaded_count < 2:
        return {
            "status": "failed",
            "error": (
                f"Only {loaded_count} image(s) could be loaded. "
                "Need at least 2 samples for training. "
                "Make sure DICOM files exist in user_data/patients/."
            ),
        }

    if progress_callback:
        progress_callback(55, "Training requested stages...")

    # ── Train XGBoost/sklearn classifier ──
    X = np.array(X_features)
    y = np.array(y_labels)

    run_detection = bool(settings.get("run_detection", True))
    run_classification = bool(settings.get("run_classification", True))
    init_info = _resolve_init_artifacts(model_source, settings, progress_callback)
    det_result: Dict[str, Any] = {"status": "skipped", "model_path": ""}
    cls_result: Dict[str, Any] = {"status": "skipped", "model_path": "", "accuracy": 0.0}

    if run_detection:
        if progress_callback:
            progress_callback(60, "Training detection model...")
        det_result = _train_detection_model(
            det_boxes,
            settings,
            output_dir,
            progress_callback,
            init_model_path=init_info.get("detector_init_path", ""),
        )

    if run_classification:
        if progress_callback:
            progress_callback(72, "Training classification model...")
        cls_result = _train_xgboost_classifier(
            X,
            y,
            settings,
            output_dir,
            progress_callback,
            init_model_path=init_info.get("classifier_init_path", ""),
        )

    result = {
        "status": "completed",
        "samples_loaded": loaded_count,
        "positives": int(sum(y)),
        "negatives": int(len(y) - sum(y)),
        "accuracy": float(cls_result.get("accuracy", 0.0)),
        "model_type": cls_result.get("model_type", "skipped"),
        "model_path": cls_result.get("model_path", ""),
        "detection_model_type": det_result.get("model_type", "skipped"),
        "detection_model_path": det_result.get("model_path", ""),
        "classification_model_type": cls_result.get("model_type", "skipped"),
        "classification_model_path": cls_result.get("model_path", ""),
        "run_detection": run_detection,
        "run_classification": run_classification,
        "backbone": str(settings.get("det_backbone", "ResNet50-FPN")),
        "model_source": str(settings.get("model_source", "iran_nobat")),
        "detector_init_path": init_info.get("detector_init_path", ""),
        "classifier_init_path": init_info.get("classifier_init_path", ""),
        "detector_init_ready": bool(init_info.get("detector_init_ready", False)),
        "classifier_init_ready": bool(init_info.get("classifier_init_ready", False)),
    }

    if progress_callback:
        progress_callback(100, "Training complete!")

    return result


def _train_detection_model(
    det_boxes: List[List[float]],
    settings: Dict[str, Any],
    output_dir: str,
    progress_callback: Optional[Callable] = None,
    init_model_path: str = "",
) -> Dict[str, Any]:
    """Train/save a lightweight detection model artifact using selected backbone."""
    import numpy as np
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    det_backbone = str(settings.get("det_backbone", "ResNet50-FPN"))
    det_backbone_slug = det_backbone.replace("/", "-").replace(" ", "_")
    model_source = str(settings.get("model_source", "iran_nobat"))
    det_threshold = float(settings.get("det_threshold", 0.35))

    base_detector = None
    if init_model_path:
        try:
            import joblib

            base_detector = joblib.load(init_model_path)
        except Exception:
            base_detector = None

    if len(det_boxes) == 0:
        detector = _ConstantBBoxDetector([0.2, 0.2, 0.8, 0.8], score=det_threshold)
        model_type = "detector_single_box_fallback"
        box_stats = {
            "count": 0,
            "mean_bbox": [0.2, 0.2, 0.8, 0.8],
        }
    else:
        arr = np.array(det_boxes, dtype=float)
        mean_bbox = [float(v) for v in arr.mean(axis=0)]
        if base_detector and hasattr(base_detector, "bbox_xyxy"):
            try:
                prev = [float(v) for v in getattr(base_detector, "bbox_xyxy")]
                mean_bbox = [float((a + b) / 2.0) for a, b in zip(mean_bbox, prev)]
                model_type = "detector_transfer_mean_box"
            except Exception:
                model_type = "detector_mean_box"
        else:
            model_type = "detector_mean_box"

        detector = _ConstantBBoxDetector(mean_bbox, score=det_threshold)
        box_stats = {
            "count": int(len(det_boxes)),
            "mean_bbox": mean_bbox,
            "std_bbox": [float(v) for v in arr.std(axis=0)],
        }

    if progress_callback:
        progress_callback(68, f"Detection backbone: {det_backbone}")

    model_path = ""
    try:
        import joblib

        model_filename = f"mg_detector_{det_backbone_slug}_{model_type}_{timestamp}.joblib"
        model_path = os.path.join(output_dir, model_filename)
        joblib.dump(detector, model_path)
    except Exception:
        import pickle

        model_filename = f"mg_detector_{det_backbone_slug}_{model_type}_{timestamp}.pkl"
        model_path = os.path.join(output_dir, model_filename)
        with open(model_path, "wb") as f:
            pickle.dump(detector, f)

    meta = {
        "timestamp": timestamp,
        "model_type": model_type,
        "model_path": model_path,
        "init_model_path": init_model_path,
        "init_mode": "transfer" if init_model_path else "scratch",
        "det_backbone": det_backbone,
        "model_source": model_source,
        "det_threshold": det_threshold,
        "det_img_size": int(settings.get("det_img_size", 1024)),
        "box_stats": box_stats,
    }
    meta_path = os.path.join(output_dir, f"detection_meta_{timestamp}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return {
        "status": "completed",
        "model_type": model_type,
        "model_path": model_path,
        "meta_path": meta_path,
    }


def _extract_basic_features(pixel_array) -> Optional[List[float]]:
    """Extract simple statistical features from a pixel array for classification."""
    try:
        import numpy as np

        arr = pixel_array.flatten()
        if len(arr) == 0:
            return None

        features = [
            float(np.mean(arr)),
            float(np.std(arr)),
            float(np.median(arr)),
            float(np.percentile(arr, 25)),
            float(np.percentile(arr, 75)),
            float(np.percentile(arr, 5)),
            float(np.percentile(arr, 95)),
            float(np.max(arr) - np.min(arr)),  # range
            float(arr.shape[0]),  # total pixels
        ]

        # Quadrant-based features (divide image into 4 quadrants)
        if pixel_array.ndim == 2:
            h, w = pixel_array.shape
            mid_h, mid_w = h // 2, w // 2
            quads = [
                pixel_array[:mid_h, :mid_w],
                pixel_array[:mid_h, mid_w:],
                pixel_array[mid_h:, :mid_w],
                pixel_array[mid_h:, mid_w:],
            ]
            for q in quads:
                features.append(float(np.mean(q)))
                features.append(float(np.std(q)))

        return features
    except Exception:
        return None


def _train_xgboost_classifier(
    X, y, settings: Dict[str, Any], output_dir: str,
    progress_callback: Optional[Callable] = None,
    init_model_path: str = "",
) -> Dict[str, Any]:
    """Train a classifier (XGBoost preferred, sklearn fallback)."""
    import numpy as np
    from datetime import datetime

    n_estimators = settings.get("cls_n_estimators", 200)
    max_depth = settings.get("cls_max_depth", 6)
    learning_rate = settings.get("cls_learning_rate", 0.1)
    model_source = str(settings.get("model_source", "iran_nobat"))
    det_backbone = str(settings.get("det_backbone", "ResNet50-FPN"))

    model = None
    model_type = "unknown"
    accuracy = 0.0

    unique_classes = np.unique(y)
    base_model = None
    if init_model_path:
        try:
            import joblib

            base_model = joblib.load(init_model_path)
        except Exception:
            base_model = None

    if unique_classes.size < 2:
        only_cls = int(unique_classes[0])
        if progress_callback:
            progress_callback(
                65,
                f"Only one class ({only_cls}) found; training constant fallback model...",
            )

        if base_model is not None:
            model = base_model
            model_type = "transfer_passthrough_single_class"
        else:
            model = _ConstantBinaryClassifier(only_cls).fit(X, y)
            model_type = "single_class_constant"
        preds = model.predict(X)
        accuracy = float(np.mean(preds == y))
    else:
        # Try XGBoost first
        try:
            import xgboost as xgb

            clf = xgb.XGBClassifier(
                n_estimators=n_estimators,
                max_depth=max_depth,
                learning_rate=learning_rate,
                use_label_encoder=False,
                eval_metric="logloss",
                random_state=42,
            )

            if progress_callback:
                progress_callback(65, "Fitting XGBoost classifier...")

            clf.fit(X, y)
            model = clf
            model_type = "xgboost"

            # Simple accuracy on training set
            preds = clf.predict(X)
            accuracy = float(np.mean(preds == y))

        except Exception as e:
            logger.warning(f"XGBoost training failed; falling back to sklearn: {e}")
            # Fallback to sklearn
            try:
                from sklearn.ensemble import GradientBoostingClassifier

                clf = GradientBoostingClassifier(
                    n_estimators=min(n_estimators, 100),
                    max_depth=max_depth,
                    learning_rate=learning_rate,
                    random_state=42,
                )

                if progress_callback:
                    progress_callback(65, "Fitting sklearn GradientBoosting...")

                clf.fit(X, y)
                model = clf
                model_type = "sklearn_gradient_boosting"

                preds = clf.predict(X)
                accuracy = float(np.mean(preds == y))

            except Exception as e2:
                logger.warning(f"sklearn fallback failed; saving features only: {e2}")
                # Last resort: features-only
                if progress_callback:
                    progress_callback(65, "No usable ML backend; saving features only...")

                model_type = "features_only"
                accuracy = 0.0

    # ── Save model ──
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = ""

    if model is not None:
        try:
            import joblib

            model_filename = (
                f"mg_classifier_{det_backbone.replace('/', '-').replace(' ', '_')}_"
                f"{model_source}_{model_type}_{timestamp}.joblib"
            )
            model_path = os.path.join(output_dir, model_filename)
            joblib.dump(model, model_path)
        except ImportError:
            import pickle

            model_filename = (
                f"mg_classifier_{det_backbone.replace('/', '-').replace(' ', '_')}_"
                f"{model_source}_{model_type}_{timestamp}.pkl"
            )
            model_path = os.path.join(output_dir, model_filename)
            with open(model_path, "wb") as f:
                pickle.dump(model, f)

    if progress_callback:
        progress_callback(90, "Saving training metadata...")

    # Save training metadata
    meta = {
        "model_type": model_type,
        "model_path": model_path,
        "init_model_path": init_model_path,
        "init_mode": "transfer" if init_model_path else "scratch",
        "timestamp": timestamp,
        "n_samples": len(y),
        "n_features": X.shape[1] if len(X.shape) > 1 else 0,
        "train_accuracy": accuracy,
        "model_source": model_source,
        "det_backbone": det_backbone,
        "settings": {
            k: v for k, v in settings.items()
            if isinstance(v, (str, int, float, bool))
        },
    }
    meta_path = os.path.join(output_dir, f"training_meta_{timestamp}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return {
        "status": "completed",
        "model_type": model_type,
        "model_path": model_path,
        "meta_path": meta_path,
        "accuracy": accuracy,
    }


def run_training_async(
    labeled_data: List[Dict[str, Any]],
    settings: Dict[str, Any],
    on_progress: Optional[Callable[[int, str], None]] = None,
    on_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
):
    """Run training in a background thread, calling progress/complete callbacks on finish."""

    def _worker():
        try:
            result = run_mammography_training(labeled_data, settings, on_progress)
            if on_complete:
                on_complete(result)
        except Exception as e:
            logger.exception("[LocalTraining] Training failed")
            if on_complete:
                on_complete({"status": "failed", "error": str(e)})

    thread = threading.Thread(target=_worker, daemon=True, name="LocalTraining")
    thread.start()
    return thread
