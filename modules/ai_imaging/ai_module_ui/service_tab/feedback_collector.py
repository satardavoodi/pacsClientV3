# -*- coding: utf-8 -*-
"""
Feedback Collector — Scans user-labeled feedback CSVs from the imaging tab
and builds training-ready datasets for BoneAge and Mammography backends.

The imaging tab writes:
  - ATTACHMENT_PATH/<study_uid>/bone_age_feedback.csv   (DX bone age review)
  - ATTACHMENT_PATH/<study_uid>/mg_feedback.csv         (MG box confirm/reject)

This module collects ALL labeled entries across all studies and produces
structured data that can be sent to backend training APIs or used locally.
"""

import csv
import os
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


def _attachment_root() -> Path:
    """Return the ATTACHMENT_PATH used by the imaging tab."""
    try:
        from PacsClient.utils.config import ATTACHMENT_PATH
        return Path(ATTACHMENT_PATH)
    except Exception:
        try:
            from aipacs_runtime import user_data_root
            return Path(user_data_root()) / "patients" / "attachments"
        except Exception:
            return Path(os.getcwd()) / "user_data" / "patients" / "attachments"


def _read_csv_safe(path: Path) -> List[Dict[str, str]]:
    """Read a CSV file, returning list of dicts. Returns [] on error."""
    if not path.exists():
        return []
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception as e:
        logger.warning(f"Failed to read CSV {path}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# BoneAge Feedback Collection
# ─────────────────────────────────────────────────────────────────────────────

def collect_bone_age_labels(study_uids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Collect all bone age feedback entries that have been reviewed/confirmed/corrected.

    Returns list of dicts with keys:
      - study_uid, patient_id, validation_status
      - ai_bone_age_months, corrected_bone_age_months
      - ai_sex, corrected_sex
      - dicom_path (resolved from study folder)

    Only entries with validation_status in ('confirmed', 'corrected') are included
    as usable training labels.
    """
    root = _attachment_root()
    if not root.exists():
        return []

    results = []
    scan_dirs = []

    if study_uids:
        scan_dirs = [root / uid for uid in study_uids if (root / uid).is_dir()]
    else:
        # Scan all study folders
        try:
            scan_dirs = [d for d in root.iterdir() if d.is_dir()]
        except Exception:
            return []

    for study_dir in scan_dirs:
        feedback_path = study_dir / "bone_age_feedback.csv"
        rows = _read_csv_safe(feedback_path)
        for row in rows:
            status = (row.get("validation_status") or "").strip().lower()
            if status not in ("confirmed", "corrected"):
                continue

            # Resolve the actual label (corrected if available, else AI prediction)
            corrected_months = row.get("corrected_bone_age_months", "").strip()
            ai_months = row.get("ai_bone_age_months", "").strip()
            corrected_sex = row.get("corrected_sex", "").strip()
            ai_sex = row.get("ai_sex", "").strip()

            label_months = corrected_months if corrected_months else ai_months
            label_sex = corrected_sex if corrected_sex else ai_sex

            if not label_months:
                continue  # No usable label

            # Find DICOM images for this study
            study_uid = row.get("study_instance_uid") or row.get("case_id") or study_dir.name
            dicom_dir = _find_dicom_dir_for_study(study_uid)

            results.append({
                "study_uid": study_uid,
                "patient_id": row.get("patient_id", ""),
                "validation_status": status,
                "label_months": float(label_months) if label_months else None,
                "label_sex": label_sex or "female",
                "ai_months": float(ai_months) if ai_months else None,
                "corrected_months": float(corrected_months) if corrected_months else None,
                "corrected_sex": corrected_sex,
                "dicom_dir": str(dicom_dir) if dicom_dir else "",
                "source_file": str(feedback_path),
            })

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Mammography Feedback Collection
# ─────────────────────────────────────────────────────────────────────────────

def collect_mammography_labels(study_uids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Collect all mammography feedback entries with reviewed box labels.

    Returns list of dicts with keys:
      - study_uid, patient_id
      - corrected_status ('abnormal' or 'normal')
      - ai_box, corrected_box (as coordinate lists)
      - ai_classification, corrected_classification
      - laterality, view
      - image_path (dicom_full_path or png)

    Only entries with validation_status='reviewed' AND a definitive corrected_status
    are included as usable training labels.
    """
    root = _attachment_root()
    if not root.exists():
        return []

    results = []
    scan_dirs = []

    if study_uids:
        scan_dirs = [root / uid for uid in study_uids if (root / uid).is_dir()]
    else:
        try:
            scan_dirs = [d for d in root.iterdir() if d.is_dir()]
        except Exception:
            return []

    for study_dir in scan_dirs:
        feedback_path = study_dir / "mg_feedback.csv"
        rows = _read_csv_safe(feedback_path)
        for row in rows:
            corrected_status = (row.get("corrected_status") or "").strip().lower()
            if corrected_status not in ("abnormal", "normal"):
                continue

            study_uid = row.get("study_instance_uid") or row.get("case_id") or study_dir.name

            # Parse box coordinates
            ai_box = _parse_box_string(row.get("ai_box", ""))
            corrected_box = _parse_box_string(row.get("corrected_box", ""))

            # Use corrected box if abnormal, otherwise mark as negative
            label_box = corrected_box if (corrected_status == "abnormal" and corrected_box) else ai_box

            results.append({
                "study_uid": study_uid,
                "patient_id": row.get("patient_id", ""),
                "corrected_status": corrected_status,
                "is_positive": corrected_status == "abnormal",
                "ai_box": ai_box,
                "corrected_box": corrected_box,
                "label_box": label_box,
                "ai_classification": row.get("ai_classification", ""),
                "corrected_classification": row.get("corrected_classification", ""),
                "laterality": row.get("corrected_laterality") or row.get("ai_laterality", ""),
                "view": row.get("corrected_view") or row.get("ai_view", ""),
                "lesion_type": row.get("corrected_lesion_type") or row.get("ai_lesion_type", ""),
                "birads_category": row.get("corrected_birads_category") or row.get("ai_birads_category", ""),
                "source_csv": row.get("source_csv", ""),
                "source_row_key": row.get("source_row_key", ""),
                "source_file": str(feedback_path),
                "human_action": row.get("human_action", ""),
            })

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Also collect labels from updated_csv_with_boxes.csv (the detection CSV
# that update_csv() in imaging_tab modifies directly with box/new_box/removed)
# ─────────────────────────────────────────────────────────────────────────────

def collect_detection_csv_labels(study_uids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Collect labels from the detection CSVs that imaging_tab modifies directly.

    The user's confirm/reject in imaging_tab writes to:
      - ATTACHMENT_PATH/<study_uid>/updated_csv_with_boxes.csv
    Columns: box (original AI boxes), new_box (user-added), removed (user-rejected)

    Returns list of dicts with image path + final labeled boxes.
    """
    root = _attachment_root()
    if not root.exists():
        return []

    results = []
    scan_dirs = []

    if study_uids:
        scan_dirs = [root / uid for uid in study_uids if (root / uid).is_dir()]
    else:
        try:
            scan_dirs = [d for d in root.iterdir() if d.is_dir()]
        except Exception:
            return []

    csv_names = [
        "updated_csv_with_boxes_and_labels.csv",
        "updated_csv_with_boxes.csv",
    ]

    for study_dir in scan_dirs:
        csv_path = None
        for name in csv_names:
            candidate = study_dir / name
            if candidate.exists():
                csv_path = candidate
                break
        if not csv_path:
            continue

        rows = _read_csv_safe(csv_path)
        for row in rows:
            # Parse the three box columns
            original_boxes = _parse_box_list_string(row.get("box", ""))
            new_boxes = _parse_box_list_string(row.get("new_box", ""))
            removed_boxes = _parse_box_list_string(row.get("removed", ""))

            # Final label = (original - removed) + new_boxes
            final_boxes = [b for b in original_boxes if b not in removed_boxes]
            for nb in new_boxes:
                if nb not in final_boxes:
                    final_boxes.append(nb)

            image_path = row.get("dicom_full_path") or row.get("png_full_path") or ""
            if not image_path:
                continue

            results.append({
                "study_uid": study_dir.name,
                "image_path": image_path,
                "original_boxes": original_boxes,
                "new_boxes": new_boxes,
                "removed_boxes": removed_boxes,
                "final_boxes": final_boxes,
                "is_positive": len(final_boxes) > 0,
                "labels_pred": row.get("labels_pred", ""),
                "scores": row.get("scores", ""),
                "source_csv": str(csv_path),
            })

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Summary / Statistics
# ─────────────────────────────────────────────────────────────────────────────

def collect_all_training_data_summary() -> Dict[str, Any]:
    """
    Produce a summary of all available labeled data across both modalities.
    Useful for the training tab UI to show what data is available.
    """
    bone_age = collect_bone_age_labels()
    mg_feedback = collect_mammography_labels()
    det_csv = collect_detection_csv_labels()

    ba_confirmed = [r for r in bone_age if r["validation_status"] == "confirmed"]
    ba_corrected = [r for r in bone_age if r["validation_status"] == "corrected"]

    mg_positive = [r for r in mg_feedback if r["is_positive"]]
    mg_negative = [r for r in mg_feedback if not r["is_positive"]]

    det_positive = [r for r in det_csv if r["is_positive"]]
    det_negative = [r for r in det_csv if not r["is_positive"]]

    return {
        "bone_age": {
            "total": len(bone_age),
            "confirmed": len(ba_confirmed),
            "corrected": len(ba_corrected),
            "entries": bone_age,
        },
        "mammography_feedback": {
            "total": len(mg_feedback),
            "positive": len(mg_positive),
            "negative": len(mg_negative),
            "entries": mg_feedback,
        },
        "mammography_detection": {
            "total": len(det_csv),
            "positive": len(det_positive),
            "negative": len(det_negative),
            "entries": det_csv,
        },
    }


def build_training_payload(backend: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a full training request payload that includes both settings and
    the collected labeled data for the specified backend.

    Parameters
    ----------
    backend : str
        Either 'bone_age' or 'mammography'
    settings : dict
        The training settings from the UI (hyperparams, paths, etc.)

    Returns
    -------
    dict with keys: settings, labeled_data, summary
    """
    if backend == "bone_age":
        labeled_data = collect_bone_age_labels()
        summary = {
            "total_samples": len(labeled_data),
            "confirmed": sum(1 for r in labeled_data if r["validation_status"] == "confirmed"),
            "corrected": sum(1 for r in labeled_data if r["validation_status"] == "corrected"),
        }
    else:
        mg_feedback = collect_mammography_labels()
        det_labels = collect_detection_csv_labels()
        labeled_data = {
            "feedback_labels": mg_feedback,
            "detection_csv_labels": det_labels,
        }
        summary = {
            "feedback_total": len(mg_feedback),
            "feedback_positive": sum(1 for r in mg_feedback if r["is_positive"]),
            "feedback_negative": sum(1 for r in mg_feedback if not r["is_positive"]),
            "detection_total": len(det_labels),
            "detection_positive": sum(1 for r in det_labels if r["is_positive"]),
            "detection_negative": sum(1 for r in det_labels if not r["is_positive"]),
        }

    return {
        "settings": settings,
        "labeled_data": labeled_data,
        "summary": summary,
        "backend": backend,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_dicom_dir_for_study(study_uid: str) -> Optional[Path]:
    """Find the DICOM directory for a study (SOURCE_PATH/<study_uid>/)."""
    try:
        from PacsClient.utils.config import SOURCE_PATH
        study_path = Path(SOURCE_PATH) / study_uid
        if study_path.is_dir():
            return study_path
    except Exception:
        pass
    return None


def _parse_box_string(value: str) -> List[float]:
    """Parse a single box string like '[10.0, 20.0, 30.0, 40.0]' into a list."""
    if not value or not value.strip():
        return []
    try:
        import ast
        parsed = ast.literal_eval(value.strip())
        if isinstance(parsed, (list, tuple)) and len(parsed) == 4:
            return [float(v) for v in parsed]
    except Exception:
        pass
    return []


def _parse_box_list_string(value: str) -> List[List[float]]:
    """Parse a box list string like '[[10,20,30,40],[50,60,70,80]]' into list of boxes."""
    if not value or not value.strip():
        return []
    try:
        import ast
        parsed = ast.literal_eval(value.strip())
        if isinstance(parsed, list):
            if parsed and isinstance(parsed[0], (list, tuple)):
                return [[float(v) for v in box] for box in parsed if len(box) == 4]
            elif len(parsed) == 4:
                # Single box as flat list
                return [[float(v) for v in parsed]]
    except Exception:
        pass
    return []
