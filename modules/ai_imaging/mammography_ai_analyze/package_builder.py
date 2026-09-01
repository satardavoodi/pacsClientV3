"""Collect mammography analysis data into an LLM request package.

Mirrors the architecture of ``eagle_eye_lumbar.llm_package``: the builder
validates data on the GUI thread *before* the worker starts, so a short
or invalid study fails fast rather than after a network request has been sent.

Pure python: no Qt, no network, no I/O beyond file reads.
"""

from __future__ import annotations

import base64
import csv
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

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


class PackageError(RuntimeError):
    """The mammography data cannot be turned into a valid request."""


@dataclass
class MammographyImage:
    """One mammography image with its metadata."""

    path: Path
    laterality: str  # "R", "L", or ""
    view_position: str  # "CC", "MLO", etc.
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
    """Structured CSV data from AI detection."""

    path: Path
    content: str  # raw CSV text for the prompt
    row_count: int = 0
    columns: List[str] = field(default_factory=list)


@dataclass
class MammographyPackage:
    """Everything one Intelligent AI Analyze request needs."""

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


def _encode_image_base64(path: Path) -> str:
    """Read and base64-encode an image file."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _read_csv_content(csv_path: Path) -> MammographyCSV:
    """Read a CSV file and return structured content."""
    content = ""
    row_count = 0
    columns = []
    try:
        with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        # Count rows and get columns
        with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i == 0:
                    columns = row
                else:
                    row_count += 1
    except Exception as exc:
        logger.warning("[AI_ANALYZE][ERROR] Failed to read CSV %s: %s",
                       csv_path, exc)
        raise PackageError(f"CSV file could not be read: {exc}") from exc

    # Truncate very large CSVs to keep prompt size reasonable
    # (max ~30KB of CSV text in the prompt)
    MAX_CSV_CHARS = 30_000
    if len(content) > MAX_CSV_CHARS:
        logger.warning("[AI_ANALYZE] CSV truncated from %d to %d chars",
                       len(content), MAX_CSV_CHARS)
        content = content[:MAX_CSV_CHARS] + "\n... [truncated]"

    return MammographyCSV(
        path=csv_path,
        content=content,
        row_count=row_count,
        columns=columns,
    )


def _collect_images_from_widgets(patient_widget) -> List[MammographyImage]:
    """Collect mammography images from active viewer widgets."""
    images = []
    if patient_widget is None:
        return images

    vtk_widgets = []
    nodes = getattr(patient_widget, "lst_nodes_viewer", None) or []
    for node in nodes:
        w = getattr(node, "vtk_widget", None)
        if w is not None:
            vtk_widgets.append(w)
    node_viewers = getattr(patient_widget, "lst_node_viewers", None) or []
    for node in node_viewers:
        w = getattr(node, "widget", None)
        if w is not None and w not in vtk_widgets:
            vtk_widgets.append(w)

    seen_dicom_paths = set()

    for vtk_widget in vtk_widgets:
        laterality = ""
        view_position = ""
        dicom_path = ""
        boxes = []
        scores = []

        # Read from image_viewer metadata
        try:
            iv = getattr(vtk_widget, "image_viewer", None)
            if iv:
                meta = getattr(iv, "metadata", {}) or {}
                series_meta = meta.get("series", {})
                laterality = str(
                    series_meta.get("laterality", "") or ""
                ).upper()
                view_position = str(
                    series_meta.get("view_position", "") or ""
                ).upper()
                instances = meta.get("instances", [])
                if instances and isinstance(instances, list):
                    inst = instances[0]
                    if isinstance(inst, dict):
                        dicom_path = str(inst.get("instance_path", "") or "")
        except Exception:
            pass

        # Read boxes from CSV
        csv_path = getattr(vtk_widget, "csv_details_path", None)
        if csv_path and os.path.isfile(str(csv_path)):
            try:
                from modules.ai_imaging.ai_module_ui.csv_table import (
                    read_csv_table,
                )

                df = read_csv_table(str(csv_path))
                all_rows = []
                if hasattr(vtk_widget, "get_series_ai_data_from_df"):
                    series_data = vtk_widget.get_series_ai_data_from_df(
                        df, check_all_rows=True
                    )
                    if series_data is not None:
                        if isinstance(series_data, list):
                            for tbl in series_data:
                                if hasattr(tbl, "rows"):
                                    all_rows.extend(tbl.rows)
                        elif hasattr(series_data, "rows") and series_data.rows:
                            all_rows = series_data.rows
                    if not all_rows:
                        series_data_single = (
                            vtk_widget.get_series_ai_data_from_df(
                                df, check_all_rows=False
                            )
                        )
                        if series_data_single is not None:
                            if isinstance(series_data_single, list):
                                for tbl in series_data_single:
                                    if hasattr(tbl, "rows"):
                                        all_rows.extend(tbl.rows)
                            elif (
                                hasattr(series_data_single, "rows")
                                and series_data_single.rows
                            ):
                                all_rows = series_data_single.rows

                for row_data in all_rows:
                    if not dicom_path:
                        dicom_path = str(
                            row_data.get("dicom_full_path", "") or ""
                        )
                    box_val = row_data.get("box", "")
                    parsed_boxes = _parse_box_cell(box_val)
                    score_val = row_data.get("score", "0.5")
                    try:
                        score_f = float(score_val) if score_val else 0.5
                    except (ValueError, TypeError):
                        score_f = 0.5
                    for b in parsed_boxes:
                        boxes.append(b)
                        scores.append(score_f)
                    new_box_val = row_data.get("new_box", "")
                    for b in _parse_box_cell(new_box_val):
                        boxes.append(b)
                        scores.append(0.5)
            except Exception:
                pass

        # Read laterality/view from DICOM if not from metadata
        if (not laterality or not view_position) and dicom_path and os.path.isfile(
            str(dicom_path)
        ):
            try:
                import pydicom

                ds = pydicom.dcmread(
                    str(dicom_path), stop_before_pixels=True, force=True
                )
                if not laterality:
                    lat_val = (
                        getattr(ds, "ImageLaterality", None)
                        or getattr(ds, "Laterality", None)
                        or ""
                    )
                    laterality = str(lat_val).upper().strip()
                if not view_position:
                    vp_val = getattr(ds, "ViewPosition", None) or ""
                    view_position = str(vp_val).upper().strip()
            except Exception:
                pass

        if not dicom_path or dicom_path in seen_dicom_paths:
            continue
        seen_dicom_paths.add(dicom_path)

        # Build caption
        caption_parts = []
        if laterality:
            caption_parts.append(f"Laterality: {laterality}")
        if view_position:
            caption_parts.append(f"View: {view_position}")
        if boxes:
            caption_parts.append(f"{len(boxes)} detection(s)")
        caption = " | ".join(caption_parts) if caption_parts else "Mammography image"

        # Determine image path (prefer screenshot/annotated version)
        image_path = _resolve_image_path(vtk_widget, dicom_path)
        if image_path is None:
            continue

        images.append(
            MammographyImage(
                path=image_path,
                laterality=laterality,
                view_position=view_position,
                caption=caption,
                mime=_mime_for(image_path),
                dicom_path=dicom_path,
                boxes=boxes,
                scores=scores,
            )
        )

    return images


def _resolve_image_path(vtk_widget, dicom_path: str) -> Optional[Path]:
    """Resolve the best available image for this viewer.

    Priority: annotated screenshot → DICOM-derived image → DICOM file.
    """
    # Try to get a screenshot from the viewport capture
    try:
        iv = getattr(vtk_widget, "image_viewer", None)
        if iv is not None:
            rw = getattr(iv, "image_render_window", None)
            if rw is not None:
                from modules.viewer.viewport_capture import (
                    grab_widget_pixmap,
                )

                # Grab from the vtk_widget which contains the viewer
                pixmap = grab_widget_pixmap(vtk_widget)
                if pixmap is not None and not pixmap.isNull():
                    import tempfile

                    suffix = ".png"
                    tmp = tempfile.NamedTemporaryFile(
                        suffix=suffix, delete=False
                    )
                    tmp.close()
                    pixmap.save(tmp.name)
                    return Path(tmp.name)
    except Exception:
        pass

    # Fallback to DICOM file
    if dicom_path and os.path.isfile(dicom_path):
        return Path(dicom_path)

    return None


def _parse_box_cell(val) -> List[List[float]]:
    """Parse a box cell from CSV into list of [x0,y0,x1,y1]."""
    import ast

    if val is None or (isinstance(val, float) and __import__("math").isnan(val)):
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


def build_header(images: List[MammographyImage], csv_data: Optional[MammographyCSV],
                 study_uid: str) -> str:
    """Build the text header that accompanies the images in the request."""
    lines = [
        f"MAMMOGRAPHY ANALYSIS PACKAGE",
        f"  Study: {study_uid}",
        f"  Images: {len(images)}",
    ]

    # Group by laterality + view
    views = {}
    for img in images:
        key = f"{img.laterality or 'Unknown'}-{img.view_position or 'Unknown'}"
        views.setdefault(key, []).append(img)

    for view_key, view_images in sorted(views.items()):
        total_boxes = sum(len(img.boxes) for img in view_images)
        lines.append(
            f"  View {view_key}: {len(view_images)} image(s), "
            f"{total_boxes} detection(s)"
        )

    if csv_data:
        lines.append(
            f"  CSV: {csv_data.row_count} rows, "
            f"columns: {', '.join(csv_data.columns[:10])}"
        )

    lines.append("")
    lines.append("Images follow in order, each preceded by its caption.")
    return "\n".join(lines)


def build_package(
    study_uid: str,
    patient_widget=None,
    csv_path: Optional[str] = None,
    images: Optional[List[MammographyImage]] = None,
) -> MammographyPackage:
    """Build a complete mammography analysis package from the current UI state.

    Call this on the GUI thread to validate everything before the worker starts.
    """
    logger.info("[AI_ANALYZE] Building package for study %s", study_uid)

    if images is None:
        if patient_widget is None:
            raise PackageError("No patient widget and no pre-built image list")
        images = _collect_images_from_widgets(patient_widget)

    if not images:
        raise PackageError(
            "No mammography images found. "
            "Please verify that the image analysis has completed successfully."
        )

    logger.info("[AI_ANALYZE] Collected %d images", len(images))

    # CSV
    csv_data = None
    if csv_path and os.path.isfile(csv_path):
        try:
            csv_data = _read_csv_content(Path(csv_path))
            logger.info("[AI_ANALYZE] CSV detected: %d rows", csv_data.row_count)
        except Exception as exc:
            logger.warning("[AI_ANALYZE] CSV read failed: %s", exc)
    else:
        logger.info("[AI_ANALYZE] No CSV provided")

    header = build_header(images, csv_data, study_uid)

    package = MammographyPackage(
        study_uid=study_uid,
        images=images,
        csv_data=csv_data,
        header=header,
    )

    logger.info(
        "[AI_ANALYZE] Package built: %d images, %d annotations, csv=%s",
        package.image_count,
        package.total_annotations,
        "yes" if package.has_csv else "no",
    )
    return package
