"""Build the bounded, multi-source Eagle Eye clinical-context package.

This service is deliberately independent of Qt and of the oversized imaging UI.
It runs in the LLM worker branch and combines four forms of context:

* allowlisted facts from the canonical reception API and prior reports;
* a sanitized snapshot of the PACS series catalogue stored in ``session.json``;
* photographed history pages, including DICOM series number 100000; and
* a small overview sample from the already-built MRI capture package.

Patient names, identifiers, local paths, and filenames are never included in the
model request. Context remains a clinical prior; it is not current-study finding
evidence and it cannot override the image verifier.
"""

from __future__ import annotations

import html
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence


logger = logging.getLogger(__name__)

DEFAULT_MAX_IMAGES = 8
DEFAULT_MAX_DICOM_DOCUMENTS = 4
DEFAULT_MAX_MRI_OVERVIEWS = 4
DEFAULT_MAX_TOTAL_IMAGES = 12
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_TEXT_LENGTH = 1200
MAX_PRIOR_REPORTS = 6
CLINICAL_DOCUMENT_SERIES_NUMBER = "100000"

_SUPPORTED_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

_MIME_BY_PIL_FORMAT = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}

_GENERATED_PREFIXES = (
    "capture_",
    "screenshot_",
    "pacs_clip_",
    "eagle_eye_",
    "bone_age",
)

_SAFE_STUDY_UID = re.compile(r"^[A-Za-z0-9._-]+$")
_HTML_TAG = re.compile(r"<[^>]+>")


class ClinicalDocumentImage:
    """One local image accepted by the shared multimodal transport."""

    __slots__ = ("path", "caption", "mime", "source_kind")

    def __init__(
        self,
        path: Path,
        caption: str,
        mime: str,
        source_kind: str = "attachment_document",
    ):
        self.path = Path(path)
        self.caption = str(caption)
        self.mime = str(mime)
        self.source_kind = str(source_kind)


class ClinicalContextPackage:
    """Sanitized model input for multi-source context extraction."""

    __slots__ = (
        "session_dir",
        "study_instance_uid",
        "header",
        "images",
        "structured_facts",
        "series_inventory",
        "inventory_scope",
        "source_status",
    )

    def __init__(
        self,
        session_dir: Path,
        study_instance_uid: str,
        images: Sequence[ClinicalDocumentImage],
        *,
        structured_facts: Optional[Dict[str, Any]] = None,
        series_inventory: Optional[Sequence[Dict[str, Any]]] = None,
        inventory_scope: str = "unknown",
        source_status: Optional[Dict[str, str]] = None,
    ):
        self.session_dir = Path(session_dir)
        self.study_instance_uid = str(study_instance_uid or "")
        self.images = list(images)
        self.structured_facts = dict(structured_facts or {})
        self.series_inventory = [dict(item) for item in (series_inventory or ())]
        self.inventory_scope = _inventory_scope(inventory_scope)
        self.source_status = dict(source_status or {})
        self.header = self._build_header()

    def _build_header(self) -> str:
        facts = json.dumps(self.structured_facts, ensure_ascii=False, indent=2)
        inventory = json.dumps(self.series_inventory, ensure_ascii=False, indent=2)
        image_lines = [
            f"  {index}. {item.source_kind}: {item.caption}"
            for index, item in enumerate(self.images, start=1)
        ]
        return (
            "MULTI-SOURCE CLINICAL AND EXAMINATION CONTEXT\n"
            "SOURCE AVAILABILITY\n"
            f"{json.dumps(self.source_status, ensure_ascii=False, indent=2)}\n\n"
            "RECEPTION API FACTS\n"
            f"{facts}\n\n"
            f"FULL PACS SERIES INVENTORY (scope={self.inventory_scope})\n"
            f"{inventory}\n\n"
            "CONTEXT IMAGES IN ATTACHMENT ORDER\n"
            + ("\n".join(image_lines) if image_lines else "  none")
            + "\nTreat source labels as provenance. MRI overview images provide only "
              "broad study context; the final verifier decides findings from the "
              "complete MRI evidence package."
        )

    @property
    def image_count(self) -> int:
        return len(self.images)

    @property
    def has_context(self) -> bool:
        return bool(self.images or self.structured_facts or self.series_inventory)

    def request_document(
        self,
        stage: Any,
        model: str = "",
        backend: str = "",
        context: str = "",
    ) -> dict:
        """Return reproducible provenance without identity, paths, or filenames."""
        return {
            "prompt": dict(stage.as_dict(), text=stage.text),
            "model": str(model or ""),
            "backend": str(backend or ""),
            "context": str(context or ""),
            "evidence": {
                # Retain the established value for stored-result compatibility.
                "kind": "clinical_document_images",
                "image_count": self.image_count,
                "images": [
                    {
                        "position": index,
                        "mime": image.mime,
                        "source_kind": image.source_kind,
                    }
                    for index, image in enumerate(self.images, start=1)
                ],
                "source_status": dict(self.source_status),
                "reception_facts": dict(self.structured_facts),
                "study_series_inventory_scope": self.inventory_scope,
                "study_series_inventory": list(self.series_inventory),
            },
        }


def _attachment_root() -> Path:
    from PacsClient.utils.config import ATTACHMENT_PATH

    return Path(ATTACHMENT_PATH)


def _source_root() -> Path:
    from PacsClient.utils.config import SOURCE_PATH

    return Path(SOURCE_PATH)


def _is_generated_capture(path: Path) -> bool:
    name = path.name.lower()
    return any(name.startswith(prefix) for prefix in _GENERATED_PREFIXES)


def _validated_mime(path: Path, *, validate: bool) -> Optional[str]:
    fallback = _SUPPORTED_MIME_BY_SUFFIX.get(path.suffix.lower())
    if fallback is None:
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size <= 0 or size > MAX_IMAGE_BYTES:
        return None
    if not validate:
        return fallback

    try:
        from PIL import Image

        with Image.open(path) as image:
            detected = _MIME_BY_PIL_FORMAT.get(str(image.format or "").upper())
            image.verify()
        return detected
    except Exception:
        return None


def _clean_text(value: Any, limit: int = MAX_TEXT_LENGTH) -> str:
    if value is None:
        return ""
    raw = html.unescape(str(value))
    raw = _HTML_TAG.sub(" ", raw)
    return " ".join(raw.split())[:limit]


def _first_text(
    mapping: Dict[str, Any],
    keys: Iterable[str],
    limit: int = MAX_TEXT_LENGTH,
) -> str:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            cleaned = _clean_text(value, limit)
            if cleaned:
                return cleaned
    return ""


def _age(value: Any) -> Optional[Dict[str, Any]]:
    text = _clean_text(value, 20).upper()
    if not text:
        return None
    match = re.fullmatch(r"0*(\d{1,3})([YMWD]?)", text)
    if not match:
        return None
    number = int(match.group(1))
    unit = {
        "Y": "years",
        "M": "months",
        "W": "weeks",
        "D": "days",
        "": "years",
    }[match.group(2)]
    if number < 0 or (unit == "years" and number > 130):
        return None
    return {
        "value": number,
        "unit": unit,
        "confidence": "high",
        "source": "reception_api",
    }


def _sanitize_report(report: Any) -> Optional[Dict[str, str]]:
    if not isinstance(report, dict):
        return None
    content = _first_text(
        report,
        ("summary", "content", "findings", "html_content", "html", "report_content"),
    )
    if not content:
        return None
    return {
        "date": _first_text(
            report,
            ("date", "study_date", "StudyDate", "created_at"),
            80,
        ) or "unknown",
        "modality": _first_text(report, ("modality", "Modality"), 80) or "unknown",
        "summary": content,
        "source": "prior_reception_report",
    }


def _sanitize_reception_record(record: Any) -> Dict[str, Any]:
    """Allowlist only clinical facts that improve interpretation."""
    if not isinstance(record, dict):
        return {}
    nested = record.get("data")
    if isinstance(nested, list):
        nested = nested[0] if nested else None
    if isinstance(nested, dict):
        record = nested

    patient = record.get("patient") if isinstance(record.get("patient"), dict) else {}
    referrer = (
        record.get("referrerPhysician")
        if isinstance(record.get("referrerPhysician"), dict)
        else {}
    )
    workflow = (
        record.get("imagingWorkflow")
        if isinstance(record.get("imagingWorkflow"), dict)
        else {}
    )
    facts: Dict[str, Any] = {}
    patient_age = _age(
        patient.get("Age")
        or patient.get("age")
        or record.get("Age")
        or record.get("age")
    )
    if patient_age:
        facts["patient_age"] = patient_age

    specialty = _first_text(
        referrer,
        ("Expertise", "expertise", "Specialty", "specialty"),
        160,
    )
    if specialty:
        facts["referrer_specialty"] = specialty

    services = []
    for service in list(record.get("services") or ())[:12]:
        if not isinstance(service, dict):
            continue
        name = _first_text(service, ("Service", "service", "name", "title"), 240)
        group = _first_text(service, ("ServiceGroup", "serviceGroup", "group"), 120)
        if name or group:
            services.append({
                "service": name,
                "group": group,
                "source": "reception_api",
            })
    if services:
        facts["requested_services"] = services

    history = _first_text(
        record,
        (
            "clinicalHistory",
            "clinical_history",
            "history",
            "indication",
            "reasonForStudy",
            "reason_for_study",
            "chiefComplaint",
        ),
    ) or _first_text(
        workflow,
        ("clinicalHistory", "clinical_history", "history", "indication", "notes"),
    )
    if history:
        facts["presenting_history"] = [{
            "text": history,
            "source": "reception_api",
        }]

    prior_reports = []
    embedded = record.get("previousReports") or record.get("previous_reports") or ()
    for raw in list(embedded if isinstance(embedded, list) else ())[:MAX_PRIOR_REPORTS]:
        sanitized = _sanitize_report(raw)
        if sanitized:
            prior_reports.append(sanitized)
    if prior_reports:
        facts["previous_reports"] = prior_reports
    return facts


def _default_reception_fetch(patient_id: str) -> Optional[dict]:
    from modules.network.reception_api_config import fetch_patient_record

    return fetch_patient_record(patient_id)


def _default_history_fetch(patient_id: str, study_uid: str = "") -> List[dict]:
    """Fetch a bounded set of prior reports through existing authorities."""
    previous_ids: List[str] = []
    try:
        from modules.network.socket_patient_service import get_socket_patient_service
        from PacsClient.utils.previous_exams import (
            build_previous_exam_set,
            distinct_previous_patient_ids,
        )

        service = get_socket_patient_service()
        reception_data = service.get_reception_history_sync(patient_id=patient_id)
        status_data = service.get_patient_status_sync(patient_id)
        exam_set = build_previous_exam_set(
            current_patient_id=patient_id,
            current_study_uid=study_uid,
            reception_data=reception_data,
            status_data=status_data,
        )
        previous_ids = [
            item.patient_id
            for item in distinct_previous_patient_ids(
                exam_set,
                exclude_ids=(patient_id,),
            )
            if item.patient_id
        ][:3]
    except Exception:
        previous_ids = []

    reports: List[dict] = []
    try:
        from PacsClient.utils.report_history import normalize_reception_record_reports
    except Exception:
        normalize_reception_record_reports = None

    for previous_id in previous_ids:
        try:
            record = _default_reception_fetch(previous_id)
            normalized = (
                normalize_reception_record_reports(record, patient_id=previous_id)
                if normalize_reception_record_reports is not None
                else []
            )
            reports.extend(normalized or ())
        except Exception:
            continue

    try:
        from PacsClient.utils.database import ai_get_reception_reports

        local_reports = list(
            ai_get_reception_reports(patient_id=patient_id, status=None) or ()
        )
        reports.extend(
            report
            for report in local_reports
            if not study_uid
            or str((report or {}).get("study_uid") or "").strip() != study_uid
        )
    except Exception:
        pass
    return reports[:MAX_PRIOR_REPORTS]


def _read_session(session_dir: Path) -> Dict[str, Any]:
    try:
        document = json.loads(
            (session_dir / "session.json").read_text(encoding="utf-8")
        )
        return document if isinstance(document, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _inventory_scope(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"pacs_series_catalog", "locally_available_series_only"}:
        return normalized
    return "unknown"


def _sanitize_inventory(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out = []
    for raw in items[:80]:
        if not isinstance(raw, dict):
            continue
        try:
            count = max(0, min(int(raw.get("slice_count") or 0), 100000))
        except (TypeError, ValueError):
            count = 0
        item = {
            "series_number": _clean_text(raw.get("series_number"), 40),
            "modality": _clean_text(raw.get("modality"), 20).upper(),
            "description": _clean_text(raw.get("description"), 240),
            "protocol": _clean_text(raw.get("protocol"), 240),
            "body_part": _clean_text(raw.get("body_part"), 80),
            "plane": _clean_text(raw.get("plane"), 40).lower() or "unknown",
            "slice_count": count,
            "contrast_evidence": _clean_text(
                raw.get("contrast_evidence"),
                40,
            ).lower() or "unknown",
            "kind": _clean_text(raw.get("kind"), 40).lower() or "imaging",
        }
        if any(value not in ("", 0, "unknown") for value in item.values()):
            out.append(item)
    return out


def _attachment_images(
    study_uid: str,
    root: Path,
    *,
    limit: int,
    validate: bool,
) -> List[ClinicalDocumentImage]:
    study_dir = root / study_uid
    try:
        resolved_root = root.resolve()
        resolved_study_dir = study_dir.resolve()
        if resolved_study_dir.parent != resolved_root:
            return []
        candidates = [
            path
            for path in study_dir.iterdir()
            if path.is_file()
            and not path.is_symlink()
            and path.resolve().parent == resolved_study_dir
            and path.suffix.lower() in _SUPPORTED_MIME_BY_SUFFIX
            and not _is_generated_capture(path)
        ]
    except (FileNotFoundError, NotADirectoryError, OSError):
        return []

    def newest_first(path: Path):
        try:
            return (-path.stat().st_mtime_ns, path.name.lower())
        except OSError:
            return (0, path.name.lower())

    candidates.sort(key=newest_first)
    accepted = []
    for path in candidates:
        mime = _validated_mime(path, validate=validate)
        if mime:
            accepted.append((path, mime))
        if len(accepted) >= limit:
            break
    total = len(accepted)
    return [
        ClinicalDocumentImage(
            path,
            f"Clinical document {index} of {total}",
            mime,
            "attachment_document",
        )
        for index, (path, mime) in enumerate(accepted, start=1)
    ]


def _dicom_document_images(
    study_uid: str,
    source_root: Path,
    session_dir: Path,
    *,
    limit: int,
) -> tuple[List[ClinicalDocumentImage], str]:
    """Render DICOMized clinical pages to derived PNGs without source writes."""
    series_dir = source_root / study_uid / CLINICAL_DOCUMENT_SERIES_NUMBER
    try:
        candidates = sorted(
            path
            for path in series_dir.iterdir()
            if path.is_file() and not path.is_symlink()
        )[:limit]
    except (FileNotFoundError, NotADirectoryError, OSError):
        return [], "unavailable"
    if not candidates:
        return [], "unavailable"

    output_dir = session_dir / ".context" / "documents"
    images: List[ClinicalDocumentImage] = []
    unreadable = False
    for index, source in enumerate(candidates, start=1):
        try:
            import numpy as np
            import pydicom
            from PIL import Image

            dataset = pydicom.dcmread(str(source), force=True)
            if (
                str(getattr(dataset, "SeriesNumber", "")).strip()
                != CLINICAL_DOCUMENT_SERIES_NUMBER
            ):
                continue
            array = np.asarray(dataset.pixel_array)
            if array.ndim == 4:
                array = array[0]
            elif array.ndim == 3 and array.shape[-1] not in (3, 4):
                array = array[0]
            if array.ndim not in (2, 3):
                raise ValueError("unsupported DICOM document pixel shape")

            if array.ndim == 2:
                finite = np.asarray(array, dtype=np.float32)
                low = float(np.nanmin(finite))
                high = float(np.nanmax(finite))
                if high > low:
                    finite = (finite - low) * (255.0 / (high - low))
                else:
                    finite = np.zeros_like(finite)
                array = np.clip(finite, 0, 255).astype(np.uint8)
                if (
                    str(getattr(dataset, "PhotometricInterpretation", "")).upper()
                    == "MONOCHROME1"
                ):
                    array = 255 - array
                mode = "L"
            else:
                if array.dtype != np.uint8:
                    finite = np.asarray(array, dtype=np.float32)
                    low = float(np.nanmin(finite))
                    high = float(np.nanmax(finite))
                    if high > low:
                        finite = (finite - low) * (255.0 / (high - low))
                    array = np.clip(finite, 0, 255).astype(np.uint8)
                if array.shape[-1] == 4:
                    array = array[..., :3]
                mode = "RGB"

            output_dir.mkdir(parents=True, exist_ok=True)
            target = output_dir / f"clinical_document_{index:02d}.png"
            Image.fromarray(array, mode=mode).save(target, format="PNG")
            images.append(
                ClinicalDocumentImage(
                    target,
                    f"DICOMIZED CLINICAL DOCUMENT page {len(images) + 1}",
                    "image/png",
                    "dicomized_clinical_document",
                )
            )
        except Exception:
            unreadable = True
    if images:
        return images, "available"
    return [], "unreadable" if unreadable else "unavailable"


def _evenly_sample(items: Sequence[Any], limit: int) -> List[Any]:
    if limit <= 0 or not items:
        return []
    if len(items) <= limit:
        return list(items)
    if limit == 1:
        return [items[len(items) // 2]]
    indexes = [
        round(index * (len(items) - 1) / (limit - 1))
        for index in range(limit)
    ]
    return [items[index] for index in indexes]


def _mri_overview_images(
    analysis_package: Any,
    *,
    limit: int,
) -> List[ClinicalDocumentImage]:
    if analysis_package is None or limit <= 0:
        return []
    grouped: Dict[str, List[Any]] = {}
    for image in list(getattr(analysis_package, "images", ()) or ()):
        grouped.setdefault(
            str(getattr(image, "session", "unknown") or "unknown"),
            [],
        ).append(image)
    if not grouped:
        return []

    sessions = list(grouped)
    base = max(1, limit // len(sessions))
    selected = []
    for name in sessions:
        selected.extend(_evenly_sample(grouped[name], base))
    if len(selected) < limit:
        remaining = [
            item
            for name in sessions
            for item in grouped[name]
            if item not in selected
        ]
        selected.extend(_evenly_sample(remaining, limit - len(selected)))
    selected = selected[:limit]
    out = []
    for index, item in enumerate(selected, start=1):
        path = Path(getattr(item, "path", ""))
        if not path.is_file():
            continue
        session = _clean_text(
            getattr(item, "session", "unknown"),
            40,
        ) or "unknown"
        out.append(
            ClinicalDocumentImage(
                path,
                f"MRI OVERVIEW {index} of {len(selected)} ({session} sweep)",
                str(
                    getattr(item, "mime", "")
                    or _SUPPORTED_MIME_BY_SUFFIX.get(
                        path.suffix.lower(),
                        "image/png",
                    )
                ),
                "mri_overview",
            )
        )
    return out


def empty_context_package(study_uid: str, session_dir: Any) -> ClinicalContextPackage:
    return ClinicalContextPackage(Path(session_dir), study_uid, ())


def build_context_package(
    study_uid: str,
    session_dir: Any,
    *,
    analysis_package: Any = None,
    attachment_root: Optional[Any] = None,
    source_root: Optional[Any] = None,
    reception_fetch: Optional[Callable[[str], Any]] = None,
    history_fetch: Optional[Callable[..., Any]] = None,
    max_images: int = DEFAULT_MAX_IMAGES,
    max_dicom_documents: int = DEFAULT_MAX_DICOM_DOCUMENTS,
    max_mri_overviews: int = DEFAULT_MAX_MRI_OVERVIEWS,
    validate_images: bool = True,
) -> ClinicalContextPackage:
    """Collect bounded context using existing reception and PACS authorities."""
    root = Path(session_dir)
    normalized_study_uid = str(study_uid or "").strip()
    if (
        not normalized_study_uid
        or not _SAFE_STUDY_UID.fullmatch(normalized_study_uid)
    ):
        return empty_context_package(study_uid, root)

    document = _read_session(root)
    patient_id = str(document.get("patient_id") or "").strip()
    facts: Dict[str, Any] = {}
    status = {
        "reception_api": "unavailable",
        "prior_reports": "unavailable",
        "pacs_series_inventory": "unavailable",
        "attachment_documents": "unavailable",
        "dicomized_clinical_document": "unavailable",
        "mri_overview": "unavailable",
    }

    fetch_record = reception_fetch or _default_reception_fetch
    if patient_id:
        try:
            reception_record = fetch_record(patient_id)
        except Exception:
            reception_record = None
        facts.update(_sanitize_reception_record(reception_record))
        status["reception_api"] = (
            "available" if reception_record else "unavailable"
        )

        fetch_history = history_fetch or _default_history_fetch
        try:
            raw_history = fetch_history(patient_id, normalized_study_uid)
        except TypeError:
            raw_history = fetch_history(patient_id)
        except Exception:
            raw_history = []
        reports = list(facts.get("previous_reports") or ())
        for raw in list(raw_history or ())[:MAX_PRIOR_REPORTS]:
            sanitized = _sanitize_report(raw)
            if sanitized:
                reports.append(sanitized)
        if reports:
            facts["previous_reports"] = reports[:MAX_PRIOR_REPORTS]
            status["prior_reports"] = "available"

    inventory_scope = _inventory_scope(
        document.get("study_series_inventory_scope")
    )
    inventory = _sanitize_inventory(document.get("study_series_inventory"))
    if inventory:
        status["pacs_series_inventory"] = (
            "available"
            if inventory_scope == "pacs_series_catalog"
            else "limited"
        )

    attachment_limit = max(0, min(int(max_images), DEFAULT_MAX_IMAGES))
    attachment_images = _attachment_images(
        normalized_study_uid,
        Path(attachment_root) if attachment_root is not None else _attachment_root(),
        limit=attachment_limit,
        validate=validate_images,
    )
    if attachment_images:
        status["attachment_documents"] = "available"

    dicom_images, dicom_status = _dicom_document_images(
        normalized_study_uid,
        Path(source_root) if source_root is not None else _source_root(),
        root,
        limit=max(
            0,
            min(int(max_dicom_documents), DEFAULT_MAX_DICOM_DOCUMENTS),
        ),
    )
    status["dicomized_clinical_document"] = dicom_status

    overview_images = _mri_overview_images(
        analysis_package,
        limit=max(
            0,
            min(int(max_mri_overviews), DEFAULT_MAX_MRI_OVERVIEWS),
        ),
    )
    if overview_images:
        status["mri_overview"] = "available"

    attachment_budget = max(
        0,
        DEFAULT_MAX_TOTAL_IMAGES - len(dicom_images) - len(overview_images),
    )
    attachment_images = attachment_images[:attachment_budget]
    images = attachment_images + dicom_images + overview_images
    logger.info(
        "[EAGLE-EYE-CONTEXT] selected %d context image(s) from bounded sources",
        len(images),
    )
    return ClinicalContextPackage(
        root,
        normalized_study_uid,
        images,
        structured_facts=facts,
        series_inventory=inventory,
        inventory_scope=inventory_scope,
        source_status=status,
    )
