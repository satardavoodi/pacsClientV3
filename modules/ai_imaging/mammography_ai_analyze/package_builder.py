"""Collect mammography analysis data into an LLM request package.

Strategy:
1. Read BOTH CSVs: detection CSV (local DICOM paths) + classification CSV (box coordinates)
2. Merge them by DICOM filename to get local paths + boxes
3. For each series, load the DICOM and DRAW the bounding boxes on it
4. Send annotated images + complete CSV to the model

Pure python: no Qt, no network, no I/O beyond file reads.
"""

from __future__ import annotations

import ast
import csv
import logging
import math
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .analysis_prompt import SYSTEM_PROMPT, prompt_metadata

logger = logging.getLogger(__name__)

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

_BOX_COLOR = (0, 200, 0)
_NEW_BOX_COLOR = (255, 165, 0)
_BOX_LINE_WIDTH = 3


class PackageError(RuntimeError):
    """The mammography data cannot be turned into a valid request."""


@dataclass
class MammographyImage:
    path: Path
    laterality: str
    view_position: str
    caption: str
    mime: str = "image/png"
    dicom_path: str = ""
    boxes: List[List[float]] = field(default_factory=list)
    scores: List[float] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "file": self.path.name,
            "laterality": self.laterality,
            "view": self.view_position,
            "caption": self.caption,
            "box_count": len(self.boxes),
        }


@dataclass
class MammographyCSV:
    path: Path
    content: str
    row_count: int = 0
    columns: List[str] = field(default_factory=list)


@dataclass
class MammographyPackage:
    study_uid: str
    images: List[MammographyImage]
    csv_data: Optional[MammographyCSV]
    header: str
    system_prompt: str = SYSTEM_PROMPT
    prompt_meta: Dict[str, str] = field(default_factory=prompt_metadata)

    @property
    def image_count(self) -> int:
        return len(self.images)

    @property
    def has_csv(self) -> bool:
        return self.csv_data is not None and self.csv_data.row_count > 0

    @property
    def total_annotations(self) -> int:
        return sum(len(img.boxes) for img in self.images)


def _mime_for(path: Path) -> str:
    return _MIME_BY_SUFFIX.get(path.suffix.lower(), "image/png")


def _read_csv_content(csv_path: Path) -> MammographyCSV:
    content = ""
    row_count = 0
    columns = []
    try:
        with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i == 0:
                    columns = row
                else:
                    row_count += 1
    except Exception as exc:
        logger.warning("[AI_ANALYZE][ERROR] Failed to read CSV %s: %s", csv_path, exc)
        raise PackageError(f"CSV file could not be read: {exc}") from exc

    MAX_CSV_CHARS = 30_000
    if len(content) > MAX_CSV_CHARS:
        content = content[:MAX_CSV_CHARS] + "\n... [truncated]"

    return MammographyCSV(path=csv_path, content=content, row_count=row_count, columns=columns)


def _parse_box_cell(val) -> List[List[float]]:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return []
    if isinstance(val, list):
        return val
    s = str(val).strip()
    if not s:
        return []
    try:
        data = ast.literal_eval(s)
    except Exception:
        return []
    if isinstance(data, (list, tuple)) and len(data) == 4:
        return [list(map(float, data))]
    if isinstance(data, (list, tuple)) and all(
        isinstance(x, (list, tuple)) and len(x) == 4 for x in data
    ):
        return [list(map(float, x)) for x in data]
    return []


def _load_dicom_pixels(dicom_path: str):
    try:
        import pydicom
        ds = pydicom.dcmread(dicom_path, force=True)
        pixel_array = getattr(ds, "pixel_array", None)
        if pixel_array is None:
            return None
        rows = int(getattr(ds, "Rows", pixel_array.shape[0]))
        cols = int(getattr(ds, "Columns", pixel_array.shape[1]))
        laterality = str(getattr(ds, "ImageLaterality", "") or "").upper().strip()
        view_position = str(getattr(ds, "ViewPosition", "") or "").upper().strip()
        wc = getattr(ds, "WindowCenter", None)
        ww = getattr(ds, "WindowWidth", None)
        if isinstance(wc, (list,)):
            wc = float(wc[0])
        elif wc is not None:
            wc = float(wc)
        if isinstance(ww, (list,)):
            ww = float(ww[0])
        elif ww is not None:
            ww = float(ww)
        return {
            "pixel_array": pixel_array, "rows": rows, "cols": cols,
            "laterality": laterality, "view_position": view_position,
            "window_center": wc, "window_width": ww,
        }
    except Exception as exc:
        logger.warning("[AI_ANALYZE] Failed to load DICOM %s: %s", dicom_path, exc)
        return None


def _dicom_to_pil_image(dicom_info: dict):
    import numpy as np
    from PIL import Image
    pixel_array = dicom_info["pixel_array"]
    wc = dicom_info.get("window_center")
    ww = dicom_info.get("window_width")
    if wc is not None and ww is not None and ww > 0:
        min_val = wc - ww // 2
        max_val = wc + ww // 2
        display = np.clip(pixel_array, min_val, max_val)
        display = ((display - min_val) / (max_val - min_val) * 255).astype(np.uint8)
    else:
        p_min = np.percentile(pixel_array, 1)
        p_max = np.percentile(pixel_array, 99)
        if p_max > p_min:
            display = ((pixel_array.astype(float) - p_min) / (p_max - p_min) * 255)
            display = np.clip(display, 0, 255).astype(np.uint8)
        else:
            display = np.zeros((dicom_info["rows"], dicom_info["cols"]), dtype=np.uint8)
    if display.ndim == 3:
        display = display[0] if display.shape[0] == 1 else display[:, :, 0]
    return Image.fromarray(display, mode="L")


def _draw_boxes_on_image(pil_image, boxes: List[List[float]], color=(0, 200, 0)):
    from PIL import Image, ImageDraw
    if pil_image.mode != "RGB":
        img = pil_image.convert("RGB")
    else:
        img = pil_image.copy()
    draw = ImageDraw.Draw(img)
    for box in boxes:
        if len(box) != 4:
            continue
        x0, y0, x1, y1 = box
        draw.rectangle([x0, y0, x1, y1], outline=color, width=_BOX_LINE_WIDTH)
    return img


def _convert_dicom_to_png(dicom_path: str) -> Optional[Path]:
    """Convert a raw DICOM to a PNG so the LLM API can read it."""
    dicom_info = _load_dicom_pixels(dicom_path)
    if dicom_info is None:
        return None
    pil_image = _dicom_to_pil_image(dicom_info)
    if pil_image is None:
        return None
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    pil_image.save(tmp.name, "PNG")
    return Path(tmp.name)


def _create_annotated_image(dicom_path: str, boxes: List[List[float]], scores: List[float]) -> Optional[Path]:
    dicom_info = _load_dicom_pixels(dicom_path)
    if dicom_info is None:
        return None
    pil_image = _dicom_to_pil_image(dicom_info)
    if pil_image is None:
        return None
    annotated = _draw_boxes_on_image(pil_image, boxes, color=_BOX_COLOR)
    try:
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(annotated)
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except OSError:
            try:
                font = ImageFont.load_default(size=14)
            except TypeError:
                font = ImageFont.load_default()
        for i, (box, score) in enumerate(zip(boxes, scores)):
            if len(box) != 4:
                continue
            x0, y0 = box[0], box[1]
            label = f"#{i+1} {score:.2f}"
            bbox = draw.textbbox((x0, y0 - 20), label, font=font)
            draw.rectangle(bbox, fill=(0, 0, 0))
            draw.text((x0, y0 - 20), label, fill=(0, 255, 0), font=font)
    except Exception:
        pass
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    annotated.save(tmp.name, "PNG")
    return Path(tmp.name)


def _extract_image_number(filename: str) -> str:
    """Extract the numeric ID from a DICOM filename.

    Handles: IMG-69246.dcm → 69246, Instance_69246.dcm → 69246,
             DOC-0001_pred.png → 0001, etc.
    """
    import re
    stem = os.path.splitext(filename)[0]
    # Find the last number in the stem
    m = re.search(r'(\d+)(?!.*\d)', stem)
    return m.group(1) if m else ""


def _read_classification_csv(classification_csv_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """Read classification CSV and group boxes by image numeric ID.

    Classification CSV has: laterality, view_position, xmin, ymin, xmax, ymax,
    dicom_full_path (server path), pred_No Finding, pred_Mass, etc.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}  # numeric_id → [{box, score, ...}]
    try:
        with open(classification_csv_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                xmin = row.get("xmin", "")
                ymin = row.get("ymin", "")
                xmax = row.get("xmax", "")
                ymax = row.get("ymax", "")
                if not all([xmin, ymin, xmax, ymax]):
                    continue
                try:
                    box = [float(xmin), float(ymin), float(xmax), float(ymax)]
                except (ValueError, TypeError):
                    continue

                score = 0.5
                for key in ("prob_Mass", "prob_Suspicious Calcification", "prob_Focal Asymmetry"):
                    val = row.get(key, "")
                    if val:
                        try:
                            score = max(score, float(val))
                        except (ValueError, TypeError):
                            pass

                dicom_path = str(row.get("dicom_full_path", "") or row.get("full_image_path", "") or "")
                filename = os.path.basename(dicom_path) if dicom_path else ""
                if not filename:
                    continue

                # Use numeric ID for matching (handles IMG-69246 vs Instance_69246)
                num_id = _extract_image_number(filename)
                if not num_id:
                    continue

                laterality = str(row.get("laterality", "") or "").upper().strip()
                view_position = str(row.get("view_position", "") or "").upper().strip()
                labels = str(row.get("labels_pred", "") or "")

                if num_id not in groups:
                    groups[num_id] = []
                groups[num_id].append({
                    "box": box,
                    "score": score,
                    "laterality": laterality,
                    "view_position": view_position,
                    "labels": labels,
                    "server_dicom_path": dicom_path,
                })
    except Exception as exc:
        logger.warning("[AI_ANALYZE] Classification CSV read failed: %s", exc)
    return groups


def _read_detection_csv(detection_csv_path: str) -> Dict[str, str]:
    """Read detection CSV to get local DICOM paths (keyed by filename).

    Detection CSV has: dicom_full_path (local path), box, scores.
    """
    local_paths: Dict[str, str] = {}  # filename → local dicom path
    try:
        with open(detection_csv_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dicom_path = str(row.get("dicom_full_path", "") or "")
                if not dicom_path:
                    continue
                filename = os.path.basename(dicom_path)
                if filename and filename not in local_paths:
                    local_paths[filename] = dicom_path
    except Exception as exc:
        logger.warning("[AI_ANALYZE] Detection CSV read failed: %s", exc)
    return local_paths


def _find_classification_csv(study_uid: str) -> Optional[str]:
    """Find the classification CSV file for this study."""
    csv_dir = ATTACHMENT_PATH / study_uid
    if not csv_dir.exists():
        return None
    # Look for classification_*.csv (most recent)
    candidates = sorted(csv_dir.glob("classification_*.csv"), reverse=True)
    if candidates:
        return str(candidates[0])
    return None


# Lazy import to avoid circular dependency
def _get_attachment_path():
    from PacsClient.utils.config import ATTACHMENT_PATH
    return ATTACHMENT_PATH


ATTACHMENT_PATH = None  # Will be set lazily


def _ensure_attachment_path():
    global ATTACHMENT_PATH
    if ATTACHMENT_PATH is None:
        ATTACHMENT_PATH = _get_attachment_path()


def _find_detection_csv(study_uid: str) -> Optional[str]:
    """Find the detection CSV file for this study."""
    _ensure_attachment_path()
    csv_dir = ATTACHMENT_PATH / study_uid
    if not csv_dir.exists():
        return None
    candidates = sorted(csv_dir.glob("updated_csv_with_boxes_*.csv"), reverse=True)
    if candidates:
        return str(candidates[0])
    default = csv_dir / "updated_csv_with_boxes.csv"
    if default.exists():
        return str(default)
    return None


def _scan_study_dicoms(study_uid: str) -> Dict[str, str]:
    """Scan local DICOM directories for this study. Returns {filename: full_path}."""
    _ensure_attachment_path()
    dicoms = {}  # filename → full_path

    # Primary: user_data/patients/dicom/{study_uid}/{series}/
    try:
        from PacsClient.utils.data_paths import DICOM_IMAGES_DIR
        dicom_root = DICOM_IMAGES_DIR / study_uid
        if dicom_root.exists():
            for dcm_file in dicom_root.rglob("*.dcm"):
                name = dcm_file.name
                if name not in dicoms:
                    dicoms[name] = str(dcm_file)
            logger.info("[AI_ANALYZE] DICOM dir scan: %d files from %s", len(dicoms), dicom_root)
    except Exception as exc:
        logger.warning("[AI_ANALYZE] DICOM dir scan failed: %s", exc)

    # Fallback: scan attachment directory
    if not dicoms:
        att_root = ATTACHMENT_PATH / study_uid
        if att_root.exists():
            for dcm_file in att_root.rglob("*.dcm"):
                name = dcm_file.name
                if name not in dicoms:
                    dicoms[name] = str(dcm_file)
            logger.info("[AI_ANALYZE] Attachment dir scan: %d files", len(dicoms))

    return dicoms


def _build_annotated_images_from_csvs(
    detection_csv_path: str,
    classification_csv_path: Optional[str],
    study_uid: str,
) -> List[MammographyImage]:
    """Build annotated images by merging local DICOMs + classification CSV boxes."""
    images = []

    # 1) Find local DICOM files by scanning the study directory
    local_paths = _scan_study_dicoms(study_uid)
    logger.info("[AI_ANALYZE] Local DICOMs found: %d", len(local_paths))

    # 2) Read box data from classification CSV
    cls_groups: Dict[str, List[Dict]] = {}
    if classification_csv_path and os.path.isfile(classification_csv_path):
        cls_groups = _read_classification_csv(classification_csv_path)
        total_cls = sum(len(v) for v in cls_groups.values())
        logger.info("[AI_ANALYZE] Classification CSV: %d entries with boxes", total_cls)
        logger.info("[AI_ANALYZE] Classification filenames: %s", list(cls_groups.keys()))

    # 3) Merge: for each local DICOM, find matching classification boxes by numeric ID
    merged = {}  # local_path → {laterality, view_position, boxes, scores}
    matched = 0
    for filename, local_path in local_paths.items():
        num_id = _extract_image_number(filename)
        cls_entries = cls_groups.get(num_id, []) if num_id else []
        boxes = [e["box"] for e in cls_entries]
        scores = [e["score"] for e in cls_entries]
        laterality = cls_entries[0]["laterality"] if cls_entries else ""
        view_position = cls_entries[0]["view_position"] if cls_entries else ""

        # If no classification match, read laterality/view from DICOM header
        if not laterality or not view_position:
            try:
                import pydicom
                ds = pydicom.dcmread(local_path, stop_before_pixels=True, force=True)
                if not laterality:
                    laterality = str(getattr(ds, "ImageLaterality", "") or "").upper().strip()
                if not view_position:
                    view_position = str(getattr(ds, "ViewPosition", "") or "").upper().strip()
            except Exception:
                pass

        merged[local_path] = {
            "laterality": laterality,
            "view_position": view_position,
            "boxes": boxes,
            "scores": scores,
        }
        if boxes:
            matched += 1

    logger.info("[AI_ANALYZE] Merged: %d series, %d with boxes", len(merged), matched)

    # Create annotated images
    for local_path, data in sorted(merged.items()):
        laterality = data["laterality"]
        view_position = data["view_position"]
        boxes = data["boxes"]
        scores = data["scores"]

        caption_parts = []
        if laterality:
            caption_parts.append(f"Laterality: {laterality}")
        if view_position:
            caption_parts.append(f"View: {view_position}")
        if boxes:
            caption_parts.append(f"{len(boxes)} AI detection(s)")
        caption = " | ".join(caption_parts) if caption_parts else "Mammography image"

        # Annotated image with boxes drawn
        if boxes:
            annotated_path = _create_annotated_image(local_path, boxes, scores)
            if annotated_path is not None:
                images.append(MammographyImage(
                    path=annotated_path,
                    laterality=laterality,
                    view_position=view_position,
                    caption=f"[Annotated - AI boxes drawn] {caption}",
                    mime="image/png",
                    dicom_path=local_path,
                    boxes=boxes,
                    scores=scores,
                ))
                logger.info("[AI_ANALYZE] Annotated: %s-%s (%d boxes)", laterality, view_position, len(boxes))

        # Raw image — convert DICOM to PNG so the API can decode it
        raw_path = Path(local_path)
        raw_mime = _mime_for(raw_path)
        if raw_path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            converted = _convert_dicom_to_png(local_path)
            if converted is not None:
                raw_path = converted
                raw_mime = "image/png"
        images.append(MammographyImage(
            path=raw_path,
            laterality=laterality,
            view_position=view_position,
            caption=f"[Original] {caption}",
            mime=raw_mime,
            dicom_path=local_path,
            boxes=boxes,
            scores=scores,
        ))

    return images


def build_header(images: List[MammographyImage], csv_data: Optional[MammographyCSV],
                 study_uid: str) -> str:
    lines = [
        "MAMMOGRAPHY INTELLIGENT AI ANALYSIS",
        f"Study UID: {study_uid}",
        f"Total images: {len(images)}",
        "",
    ]
    views: Dict[str, List[MammographyImage]] = {}
    for img in images:
        key = f"{img.laterality or 'Unknown'}-{img.view_position or 'Unknown'}"
        views.setdefault(key, []).append(img)

    lines.append("Available views:")
    for view_key, view_images in sorted(views.items()):
        total_boxes = sum(len(img.boxes) for img in view_images)
        lines.append(f"  {view_key}: {total_boxes} detection(s)")

    if csv_data:
        lines.append(f"\nCSV data: {csv_data.row_count} rows, columns: {', '.join(csv_data.columns)}")

    lines.append("")
    lines.append("EACH VIEW HAS TWO IMAGES:")
    lines.append("  1. [Annotated] — image with GREEN bounding boxes drawn by AI")
    lines.append("  2. [Original] — original high-resolution image")
    lines.append("")
    lines.append("CORRELATE the visual findings on images with the structured CSV data.")
    lines.append("The green rectangles are AI-detected lesions — analyze them together with CSV.")
    return "\n".join(lines)


def build_package(
    study_uid: str,
    patient_widget=None,
    csv_path: Optional[str] = None,
    images: Optional[List[MammographyImage]] = None,
) -> MammographyPackage:
    """Build a complete mammography analysis package."""
    _ensure_attachment_path()
    logger.info("[AI_ANALYZE] Building package for study %s", study_uid)

    # Find BOTH CSVs
    det_csv = csv_path
    if not det_csv:
        det_csv = _find_detection_csv(study_uid)
    cls_csv = _find_classification_csv(study_uid)

    logger.info("[AI_ANALYZE] Detection CSV: %s", det_csv or "none")
    logger.info("[AI_ANALYZE] Classification CSV: %s", cls_csv or "none")

    # Read CSV content for prompt
    csv_data = None
    csv_for_prompt = cls_csv or det_csv
    if csv_for_prompt and os.path.isfile(csv_for_prompt):
        try:
            csv_data = _read_csv_content(Path(csv_for_prompt))
            logger.info("[AI_ANALYZE] CSV: %d rows", csv_data.row_count)
        except Exception as exc:
            logger.warning("[AI_ANALYZE] CSV read failed: %s", exc)

    # Build images from CSVs
    if images is None and det_csv and os.path.isfile(det_csv):
        logger.info("[AI_ANALYZE] Building from CSVs (det + cls)")
        images = _build_annotated_images_from_csvs(det_csv, cls_csv, study_uid)

    if not images:
        raise PackageError(
            "No mammography images found. "
            "Please verify that the image analysis has completed successfully."
        )

    # Summary
    total_boxes = sum(len(img.boxes) for img in images)
    view_set = set()
    for img in images:
        key = f"{img.laterality or '?'}-{img.view_position or '?'}"
        view_set.add(key)
    logger.info("[AI_ANALYZE] Package: %d images, %d boxes, views: %s",
                len(images), total_boxes, sorted(view_set))

    header = build_header(images, csv_data, study_uid)
    return MammographyPackage(
        study_uid=study_uid,
        images=images,
        csv_data=csv_data,
        header=header,
    )
