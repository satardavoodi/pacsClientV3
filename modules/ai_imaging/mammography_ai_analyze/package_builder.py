"""Build a bounded, de-identified mammography request package.

Only rendered mammograms and an allowlisted detection summary leave this
boundary. Raw CSV rows, DICOM identifiers, patient fields, and filesystem paths
are deliberately excluded from model-facing text.
"""

from __future__ import annotations

import ast
import csv
import json
import logging
import math
import re
import tempfile
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .analysis_prompt import SYSTEM_PROMPT, prompt_metadata
from .source_snapshot import MAX_LOCAL_SOURCE_HINTS, MammographySourceHint

logger = logging.getLogger(__name__)

MAX_SOURCE_IMAGES = 8
MAX_DETECTIONS_PER_IMAGE = 32
MAX_CSV_BYTES = 2_000_000
MAX_CSV_ROWS = 5_000
MAX_SOURCE_FILE_BYTES = 256_000_000
MAX_SOURCE_PIXELS = 64_000_000
MAX_RENDER_DIMENSION = 3072

_ALLOWED_LABELS = (
    "Architectural Distortion",
    "Suspicious Calcification",
    "Focal Asymmetry",
    "Calcification",
    "Asymmetry",
    "Mass",
    "No Finding",
)
_VIEW_RE = re.compile(r"^[A-Z0-9+_-]{1,16}$")
_NUMBER_TAIL_RE = re.compile(r"(\d+)(?!.*\d)")


class PackageError(RuntimeError):
    """The selected mammography evidence cannot be packaged safely."""


@dataclass(frozen=True)
class MammographyFinding:
    box: tuple[float, float, float, float]
    score: float
    label: str = "Unclassified AI detection"


@dataclass(frozen=True)
class MammographyImage:
    path: Path
    caption: str
    alias: str
    laterality: str
    view_position: str
    findings: tuple[MammographyFinding, ...] = field(default_factory=tuple)
    mime: str = "image/png"


class MammographyPackage:
    """One request package and its owned temporary rendered images."""

    def __init__(self, *, images: Iterable[MammographyImage], header: str, temporary):
        self.images = list(images)
        self.header = str(header)
        self.system_prompt = SYSTEM_PROMPT
        self.prompt = prompt_metadata()
        self._temporary = temporary

    @property
    def image_count(self) -> int:
        return len(self.images)

    @property
    def total_findings(self) -> int:
        return sum(len(image.findings) for image in self.images)

    def cleanup(self) -> None:
        temporary, self._temporary = self._temporary, None
        if temporary is not None:
            temporary.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.cleanup()
        return False


@dataclass
class _SourceImage:
    path: Path
    dataset: Any
    findings: list[MammographyFinding]
    laterality: str
    view_position: str


@dataclass(frozen=True)
class _ResolvedSourceHint:
    path: Path
    series_uid: str
    sop_instance_uid: str
    instance_number: int | None
    name: str
    token: str


def _read_rows(path: Path) -> list[dict[str, str]]:
    try:
        if not path.is_file():
            raise PackageError("A required mammography result file is missing.")
        if path.stat().st_size > MAX_CSV_BYTES:
            raise PackageError("A mammography result file exceeds the safe size limit.")
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = []
            for index, row in enumerate(reader):
                if index >= MAX_CSV_ROWS:
                    raise PackageError("Mammography results exceed the safe row limit.")
                rows.append({str(key): str(value or "") for key, value in row.items()})
            return rows
    except PackageError:
        raise
    except Exception as exc:
        raise PackageError("A mammography result file could not be read.") from exc


def _literal_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        parsed = ast.literal_eval(str(value).strip())
    except (SyntaxError, ValueError):
        return []
    return list(parsed) if isinstance(parsed, (list, tuple)) else [parsed]


def _parse_boxes(value: Any) -> list[tuple[float, float, float, float]]:
    parsed = _literal_list(value)
    if len(parsed) == 4 and not any(isinstance(item, (list, tuple)) for item in parsed):
        parsed = [parsed]
    boxes = []
    for item in parsed:
        if not isinstance(item, (list, tuple)) or len(item) != 4:
            continue
        try:
            box = tuple(float(part) for part in item)
        except (TypeError, ValueError):
            continue
        if all(math.isfinite(part) for part in box):
            boxes.append(box)
    return boxes


def _parse_scores(value: Any, count: int) -> list[float]:
    values = _literal_list(value)
    if not values and value not in (None, ""):
        values = [value]
    result = []
    for item in values:
        try:
            score = float(item)
        except (TypeError, ValueError):
            continue
        if math.isfinite(score):
            result.append(min(1.0, max(0.0, score)))
    if not result:
        result = [0.5]
    while len(result) < count:
        result.append(result[-1])
    return result[:count]


def _same_box(left, right, tolerance: float = 1.0) -> bool:
    return all(abs(float(a) - float(b)) <= tolerance for a, b in zip(left, right))


def _active_detection_findings(row: dict[str, str]) -> list[MammographyFinding]:
    original = _parse_boxes(row.get("box"))
    added = _parse_boxes(row.get("new_box"))
    removed = _parse_boxes(row.get("removed"))
    boxes = [box for box in original if not any(_same_box(box, old) for old in removed)]
    for box in added:
        if not any(_same_box(box, existing) for existing in boxes):
            boxes.append(box)
    scores = _parse_scores(row.get("scores") or row.get("score"), len(boxes))
    return [
        MammographyFinding(box=box, score=scores[index])
        for index, box in enumerate(boxes[:MAX_DETECTIONS_PER_IMAGE])
    ]


def _clean_label(value: Any) -> str:
    raw = str(value or "").lower()
    labels = [label for label in _ALLOWED_LABELS if label.lower() in raw]
    return " / ".join(labels) if labels else "Unclassified AI detection"


def _classification_score(row: dict[str, str]) -> float:
    candidates = [row.get("confidence"), row.get("score")]
    candidates.extend(row.get(f"prob_{label}") for label in _ALLOWED_LABELS)
    scores = _parse_scores([value for value in candidates if value not in (None, "")], 1)
    return scores[0]


def _match_keys(path_value: Any) -> tuple[str, ...]:
    name = Path(str(path_value or "").replace("\\", "/")).name.lower()
    keys = [f"name:{name}"] if name else []
    match = _NUMBER_TAIL_RE.search(Path(name).stem)
    if match:
        keys.append(f"number:{match.group(1)}")
    return tuple(keys)


def _path_identity(path_value: Any) -> tuple[str, str, str]:
    normalized = str(path_value or "").strip().strip('"').strip("'").replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    name = parts[-1].lower() if parts else ""
    parent = parts[-2] if len(parts) >= 2 else ""
    match = _NUMBER_TAIL_RE.search(Path(name).stem)
    return name, parent, (match.group(1) if match else "")


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _resolved_source_hints(
    hints: Iterable[MammographySourceHint] | None,
) -> tuple[_ResolvedSourceHint, ...]:
    if hints is None:
        return ()
    values = []
    for hint in hints:
        values.append(hint)
        if len(values) > MAX_LOCAL_SOURCE_HINTS:
            raise PackageError("The local mammography source catalogue exceeds the safe limit.")
    resolved = []
    seen = set()
    for hint in values:
        try:
            path = Path(str(hint.path or "")).resolve(strict=True)
        except (OSError, ValueError):
            continue
        key = str(path).casefold()
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        name, _, token = _path_identity(path)
        resolved.append(
            _ResolvedSourceHint(
                path=path,
                series_uid=str(hint.series_uid or "").strip(),
                sop_instance_uid=str(hint.sop_instance_uid or "").strip(),
                instance_number=_optional_int(hint.instance_number),
                name=name,
                token=token,
            )
        )
    return tuple(resolved)


def _unique_hint(candidates: Iterable[_ResolvedSourceHint]) -> Optional[Path]:
    values = {str(candidate.path).casefold(): candidate.path for candidate in candidates}
    return next(iter(values.values())) if len(values) == 1 else None


def _rebind_result_path(
    row: dict[str, str],
    hints: tuple[_ResolvedSourceHint, ...],
) -> Optional[Path]:
    path_value = row.get("dicom_full_path") or row.get("dicom_path") or row.get("path")
    if not path_value:
        return None
    if not hints:
        try:
            return Path(path_value).resolve(strict=True)
        except (OSError, ValueError):
            return None

    try:
        direct = Path(path_value).resolve(strict=True)
    except (OSError, ValueError):
        direct = None
    if direct is not None:
        match = _unique_hint(hint for hint in hints if hint.path == direct)
        if match is not None:
            return match

    name, parent_hint, token = _path_identity(path_value)
    sop_hint = str(
        row.get("sop_instance_uid")
        or row.get("sop_uid")
        or row.get("SOPInstanceUID")
        or ""
    ).strip()
    series_hint = str(
        row.get("series_instance_uid")
        or row.get("series_uid")
        or row.get("SeriesInstanceUID")
        or parent_hint
        or ""
    ).strip()
    instance_hint = _optional_int(
        row.get("instance_number") or row.get("InstanceNumber") or token
    )

    if sop_hint:
        match = _unique_hint(
            hint for hint in hints if hint.sop_instance_uid == sop_hint
        )
        if match is not None:
            return match

    series_matches = tuple(
        hint for hint in hints if series_hint and hint.series_uid == series_hint
    )
    if series_matches:
        match = _unique_hint(hint for hint in series_matches if name and hint.name == name)
        if match is not None:
            return match
        match = _unique_hint(
            hint
            for hint in series_matches
            if instance_hint is not None
            and (
                hint.instance_number == instance_hint
                or (hint.token and _optional_int(hint.token) == instance_hint)
            )
        )
        if match is not None:
            return match
        match = _unique_hint(series_matches)
        if match is not None:
            return match

    match = _unique_hint(hint for hint in hints if name and hint.name == name)
    if match is not None:
        return match
    if instance_hint is not None:
        return _unique_hint(
            hint
            for hint in hints
            if hint.instance_number == instance_hint
            or (hint.token and _optional_int(hint.token) == instance_hint)
        )
    return None


def _classification_findings(rows: list[dict[str, str]]) -> dict[str, list[MammographyFinding]]:
    result: dict[str, list[MammographyFinding]] = {}
    for row in rows:
        try:
            box = tuple(float(row.get(field, "")) for field in ("xmin", "ymin", "xmax", "ymax"))
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(part) for part in box):
            continue
        finding = MammographyFinding(
            box=box,
            score=_classification_score(row),
            label=_clean_label(row.get("labels_pred") or row.get("label")),
        )
        for key in _match_keys(row.get("dicom_full_path") or row.get("full_image_path")):
            result.setdefault(key, []).append(finding)
    return result


def _merge_findings(
    base: list[MammographyFinding],
    classified: Iterable[MammographyFinding],
) -> list[MammographyFinding]:
    merged = list(base)
    for candidate in classified:
        for index, existing in enumerate(merged):
            if _same_box(candidate.box, existing.box):
                merged[index] = MammographyFinding(
                    box=existing.box,
                    score=max(existing.score, candidate.score),
                    label=candidate.label,
                )
                break
        else:
            if len(merged) < MAX_DETECTIONS_PER_IMAGE:
                merged.append(candidate)
    return merged[:MAX_DETECTIONS_PER_IMAGE]


def _safe_csv_path(study_dir: Path, value: Any, required_prefix: str) -> Optional[Path]:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = study_dir / candidate
    try:
        candidate = candidate.resolve(strict=True)
        candidate.relative_to(study_dir)
    except (OSError, ValueError):
        return None
    if not candidate.name.lower().startswith(required_prefix) or candidate.suffix.lower() != ".csv":
        return None
    return candidate


def _latest_safe_csv(study_dir: Path, required_prefix: str) -> Optional[Path]:
    candidates = []
    for path in study_dir.glob(f"{required_prefix}*.csv"):
        candidate = _safe_csv_path(study_dir, path, required_prefix)
        if candidate is None:
            continue
        try:
            candidates.append((candidate.stat().st_mtime_ns, candidate.name, candidate))
        except OSError:
            continue
    candidates.sort(reverse=True)
    return candidates[0][2] if candidates else None


def resolve_active_csv_paths(study_uid: str, attachments_root: Path) -> tuple[Path, Optional[Path]]:
    """Resolve the active result pair while containing paths to one study folder."""
    root = Path(attachments_root).resolve()
    study_dir = (root / str(study_uid or "")).resolve()
    try:
        study_dir.relative_to(root)
    except ValueError as exc:
        raise PackageError("The mammography study identity is invalid.") from exc
    if study_dir == root:
        raise PackageError("The mammography study identity is invalid.")
    if not study_dir.is_dir():
        raise PackageError("No mammography analysis results were found for this study.")

    detection = classification = None
    manifest_path = study_dir / "mg_ai_manifest.json"
    if manifest_path.is_file() and manifest_path.stat().st_size <= MAX_CSV_BYTES:
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
            active = document.get("active") if isinstance(document, dict) else {}
            if isinstance(active, dict):
                detection = _safe_csv_path(
                    study_dir, active.get("detection"), "updated_csv_with_boxes"
                )
                classification = _safe_csv_path(
                    study_dir, active.get("classification"), "classification"
                )
        except (OSError, ValueError, json.JSONDecodeError):
            detection = classification = None

    if detection is None:
        detection = _latest_safe_csv(study_dir, "updated_csv_with_boxes")
    if classification is None:
        classification = _latest_safe_csv(study_dir, "classification")
    if detection is None:
        raise PackageError("No mammography detection result was found for this study.")
    return detection, classification


def _load_source(path: Path, expected_study_uid: str, findings: list[MammographyFinding]) -> _SourceImage:
    try:
        import pydicom

        if path.stat().st_size > MAX_SOURCE_FILE_BYTES:
            raise PackageError("A selected mammogram exceeds the safe file size limit.")
        dataset = pydicom.dcmread(str(path), force=True, defer_size=1_000_000)
        modality = str(getattr(dataset, "Modality", "") or "").upper().strip()
        if modality != "MG":
            raise PackageError("A selected source image is not a mammogram.")
        actual_study_uid = str(getattr(dataset, "StudyInstanceUID", "") or "").strip()
        if not actual_study_uid or actual_study_uid != expected_study_uid:
            raise PackageError("A selected mammogram does not belong to the requested study.")
        if "PixelData" not in dataset:
            raise PackageError("A selected mammogram has no pixel data.")
        rows = int(getattr(dataset, "Rows", 0) or 0)
        columns = int(getattr(dataset, "Columns", 0) or 0)
        frames = int(getattr(dataset, "NumberOfFrames", 1) or 1)
        samples = int(getattr(dataset, "SamplesPerPixel", 1) or 1)
        if (
            rows <= 0
            or columns <= 0
            or rows * columns > MAX_SOURCE_PIXELS
            or frames != 1
            or samples != 1
        ):
            raise PackageError("A selected mammogram has unsafe pixel dimensions.")
        laterality = str(
            getattr(dataset, "ImageLaterality", "")
            or getattr(dataset, "Laterality", "")
            or "U"
        ).upper().strip()
        laterality = laterality if laterality in {"L", "R", "B"} else "U"
        view = str(getattr(dataset, "ViewPosition", "") or "UNKNOWN").upper().strip()
        view = view if _VIEW_RE.fullmatch(view) else "UNKNOWN"
        return _SourceImage(path, dataset, findings, laterality, view)
    except PackageError:
        raise
    except Exception as exc:
        raise PackageError("A selected mammogram could not be decoded.") from exc


def _clamp_box(box, width: int, height: int) -> Optional[tuple[float, float, float, float]]:
    x0, x1 = sorted((float(box[0]), float(box[2])))
    y0, y1 = sorted((float(box[1]), float(box[3])))
    x0, x1 = max(0.0, x0), min(float(width - 1), x1)
    y0, y1 = max(0.0, y0), min(float(height - 1), y1)
    if x1 - x0 < 1.0 or y1 - y0 < 1.0:
        return None
    return x0, y0, x1, y1


def _render_source(source: _SourceImage, destination: Path) -> tuple[list[MammographyFinding], tuple[int, int]]:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    from PacsClient.pacs.patient_tab.utils.dicom_windowing import (
        auto_window_level_for_mg_array,
        normalize_window_level,
        should_invert_for_display,
        window_to_uint8,
    )

    dataset = source.dataset
    try:
        pixels = np.asarray(dataset.pixel_array)
    except Exception as exc:
        raise PackageError("A selected mammogram could not be decoded.") from exc
    if pixels.ndim == 3 and pixels.shape[0] == 1:
        pixels = pixels[0]
    if pixels.ndim != 2:
        raise PackageError("Only two-dimensional mammography source images are supported.")

    pixels = pixels.astype(np.float32, copy=False)
    slope = float(getattr(dataset, "RescaleSlope", 1.0) or 1.0)
    intercept = float(getattr(dataset, "RescaleIntercept", 0.0) or 0.0)
    if not math.isclose(slope, 1.0) or not math.isclose(intercept, 0.0):
        pixels = pixels * slope + intercept

    photometric = str(
        getattr(dataset, "PhotometricInterpretation", "MONOCHROME2") or "MONOCHROME2"
    ).upper()
    intent = str(getattr(dataset, "PresentationIntentType", "") or "").upper()
    width, center = normalize_window_level(
        getattr(dataset, "WindowWidth", None),
        getattr(dataset, "WindowCenter", None),
        treat_legacy_placeholder_as_missing=True,
        treat_mg_full_range_placeholder_as_missing=True,
        modality="MG",
        photometric=photometric,
        presentation_intent_type=intent,
    )
    if width is None or center is None:
        width, center = auto_window_level_for_mg_array(pixels)
    display = window_to_uint8(pixels, width, center)
    if should_invert_for_display(photometric, getattr(dataset, "PresentationLUTShape", None)):
        display = 255 - display

    image = Image.fromarray(display, mode="L").convert("RGB")
    original_width, original_height = image.size
    scale = min(1.0, MAX_RENDER_DIMENSION / max(original_width, original_height))
    if scale < 1.0:
        target = (max(1, round(original_width * scale)), max(1, round(original_height * scale)))
        image = image.resize(target, Image.Resampling.LANCZOS)

    findings = []
    for finding in source.findings:
        box = _clamp_box(finding.box, original_width, original_height)
        if box is not None:
            findings.append(MammographyFinding(box, finding.score, finding.label))

    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    line_width = max(3, round(min(image.size) / 450))
    for index, finding in enumerate(findings, start=1):
        scaled = tuple(round(value * scale) for value in finding.box)
        draw.rectangle(scaled, outline=(0, 220, 80), width=line_width)
        label = f"F{index} {finding.score:.2f}"
        text_box = draw.textbbox((scaled[0], max(0, scaled[1] - 22)), label, font=font)
        draw.rectangle(text_box, fill=(0, 0, 0))
        draw.text((scaled[0], max(0, scaled[1] - 22)), label, fill=(0, 255, 100), font=font)
    image.save(destination, "PNG", optimize=True)
    return findings, (original_width, original_height)


def _caption(alias: str, source: _SourceImage, findings: list[MammographyFinding]) -> str:
    if not findings:
        detail = "No structured AI detections are attached to this image."
    else:
        rows = [
            f"F{index}: {finding.label}; AI confidence {finding.score:.2f}; "
            f"box_px [{', '.join(str(round(value, 1)) for value in finding.box)}]"
            for index, finding in enumerate(findings, start=1)
        ]
        detail = " Structured detections: " + " | ".join(rows)
    return (
        f"{alias} | Laterality {source.laterality} | View {source.view_position}. "
        "Green rectangles are approximate AI pointers." + detail
    )


def _build_header(images: list[MammographyImage]) -> str:
    lines = [
        "MAMMOGRAPHY EVIDENCE PACKAGE",
        "The package is de-identified. Image aliases are local to this request.",
        f"Images: {len(images)}; structured detections: {sum(len(i.findings) for i in images)}.",
        "Use only the immediately following image captions and pixels.",
        "Available views:",
    ]
    lines.extend(
        f"- {image.alias}: {image.laterality} {image.view_position}; "
        f"{len(image.findings)} structured detection(s)"
        for image in images
    )
    return "\n".join(lines)


def build_package(
    *,
    study_uid: str,
    detection_csv_path: Path | str,
    classification_csv_path: Path | str | None = None,
    local_source_hints: Iterable[MammographySourceHint] | None = None,
) -> MammographyPackage:
    """Build one study-bound package without exposing raw identifiers or CSV."""
    if not str(study_uid or "").strip():
        raise PackageError("The mammography study identity is unavailable.")

    detection_rows = _read_rows(Path(detection_csv_path))
    classification_rows = (
        _read_rows(Path(classification_csv_path)) if classification_csv_path else []
    )
    classified = _classification_findings(classification_rows)
    source_hints = _resolved_source_hints(local_source_hints)

    grouped: "OrderedDict[Path, list[MammographyFinding]]" = OrderedDict()
    for row in detection_rows:
        path_text = row.get("dicom_full_path") or row.get("dicom_path") or row.get("path")
        if not path_text:
            continue
        path = _rebind_result_path(row, source_hints)
        if path is None:
            continue
        findings = _active_detection_findings(row)
        matches = []
        for key in _match_keys(path_text):
            matches.extend(classified.get(key, ()))
        grouped[path] = _merge_findings(grouped.get(path, []), [*findings, *matches])

    if not grouped:
        raise PackageError("No local mammography source images were found in the selected result.")
    if len(grouped) > MAX_SOURCE_IMAGES:
        raise PackageError(
            f"The selected result contains {len(grouped)} source images; "
            f"the safe request limit is {MAX_SOURCE_IMAGES}."
        )

    sources = [
        _load_source(path, str(study_uid), findings)
        for path, findings in grouped.items()
    ]
    sources.sort(key=lambda item: (item.laterality, item.view_position, item.path.name.lower()))

    temporary = tempfile.TemporaryDirectory(prefix="aipacs_mammography_")
    try:
        rendered = []
        root = Path(temporary.name)
        for index, source in enumerate(sources, start=1):
            alias = f"MG-{index:02d}"
            destination = root / f"{alias.lower()}.png"
            try:
                findings, _ = _render_source(source, destination)
            finally:
                source.dataset = None
            rendered.append(MammographyImage(
                path=destination,
                caption=_caption(alias, source, findings),
                alias=alias,
                laterality=source.laterality,
                view_position=source.view_position,
                findings=tuple(findings),
            ))
        return MammographyPackage(
            images=rendered,
            header=_build_header(rendered),
            temporary=temporary,
        )
    except Exception:
        temporary.cleanup()
        raise
