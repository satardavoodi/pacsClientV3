import csv
from datetime import datetime, timezone
from pathlib import Path


BASE_FIELD_ORDER = [
    "schema",
    "schema_version",
    "case_id",
    "patient_id",
    "study_instance_uid",
    "series_instance_uid",
    "sop_instance_uid",
    "module_name",
    "modality",
    "validation_status",
    "reviewer_id",
    "review_timestamp",
    "correction_notes",
    "export_status",
    "server_sync_status",
]


MG_FIELD_ORDER = [
    "record_id",
    "finding_uid",
    "source_csv",
    "source_row_key",
    "source_row_index",
    "source_box_index",
    "source_kind",
    "ai_box",
    "ai_classification",
    "ai_confidence",
    "ai_laterality",
    "ai_view",
    "ai_lesion_type",
    "ai_location",
    "ai_quadrant",
    "ai_clock_position",
    "ai_depth",
    "ai_birads_category",
    "corrected_box",
    "corrected_classification",
    "corrected_status",
    "corrected_laterality",
    "corrected_view",
    "corrected_lesion_type",
    "corrected_location",
    "corrected_quadrant",
    "corrected_clock_position",
    "corrected_depth",
    "corrected_birads_category",
    "corrected_confidence",
    "polygon_ijk_points",
    "polygon_world_points",
    "human_action",
]


def _normalize_sex(value):
    if value is None:
        return ""
    if isinstance(value, str):
        sex = value.strip().lower()
    else:
        sex = str(value).strip().lower()

    if sex in ("m", "male", "0"):
        return "male"
    if sex in ("f", "female", "1"):
        return "female"
    return sex


def _utc_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_csv_rows(path: Path):
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def load_feedback_row(path: Path, key_field: str, key_value: str):
    rows = _read_csv_rows(path)
    for row in rows:
        if str(row.get(key_field) or "") == str(key_value):
            return row
    return None


def _write_csv_rows(path: Path, rows, field_order):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=field_order)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in field_order})


def _ordered_fields(rows):
    seen = set()
    ordered = []
    for field in BASE_FIELD_ORDER:
        seen.add(field)
        ordered.append(field)
    for field in MG_FIELD_ORDER:
        if field not in seen:
            seen.add(field)
            ordered.append(field)
    for row in rows:
        for field in row.keys():
            if field not in seen:
                seen.add(field)
                ordered.append(field)
    return ordered


def _preserve_feedback_fields(existing_row, new_row):
    preserved = [
        "corrected_bone_age_years",
        "corrected_bone_age_months",
        "corrected_sex",
        "corrected_box",
        "corrected_classification",
        "corrected_status",
        "validation_status",
        "reviewer_id",
        "review_timestamp",
        "correction_notes",
        "export_status",
        "server_sync_status",
    ]
    for field in preserved:
        existing_value = existing_row.get(field, "")
        if existing_value not in (None, ""):
            new_row[field] = existing_value
    return new_row


def _merge_feedback_row(existing_row, new_row, *, preserve_existing_human_fields: bool):
    if preserve_existing_human_fields:
        return _preserve_feedback_fields(existing_row, new_row)
    merged = dict(existing_row or {})
    merged.update(new_row)
    return merged


def _pick(row, keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return ""


def build_bone_age_feedback_row(study_uid: str, metadata_context: dict | None, result_data: dict | None):
    metadata_context = metadata_context or {}
    result_data = result_data or {}

    patient_id = (
        metadata_context.get("patient_id")
        or metadata_context.get("patient_code")
        or metadata_context.get("PatientID")
        or ""
    )
    series_instance_uid = (
        metadata_context.get("series_instance_uid")
        or metadata_context.get("series_uid")
        or metadata_context.get("SeriesInstanceUID")
        or ""
    )
    sop_instance_uid = (
        metadata_context.get("sop_instance_uid")
        or metadata_context.get("SOPInstanceUID")
        or ""
    )

    ai_years = result_data.get("bone_age_years")
    if ai_years is None:
        ai_years = result_data.get("predicted_bone_age_years")

    ai_months = result_data.get("bone_age_months")
    if ai_months is None:
        ai_months = result_data.get("predicted_bone_age_months")

    ai_sex = _normalize_sex(result_data.get("sex"))

    return {
        "schema": "eagleeye_feedback_v1",
        "schema_version": 1,
        "case_id": study_uid,
        "patient_id": patient_id,
        "study_instance_uid": study_uid,
        "series_instance_uid": series_instance_uid,
        "sop_instance_uid": sop_instance_uid,
        "module_name": "bone_age",
        "modality": "DX",
        "ai_bone_age_years": "" if ai_years is None else ai_years,
        "ai_bone_age_months": "" if ai_months is None else ai_months,
        "ai_sex": ai_sex,
        "corrected_bone_age_years": "",
        "corrected_bone_age_months": "",
        "corrected_sex": "",
        "validation_status": "pending_review",
        "reviewer_id": "",
        "review_timestamp": "",
        "correction_notes": "",
        "export_status": "local_only",
        "server_sync_status": "not_synced",
    }


def write_bone_age_feedback_csv(study_uid: str, attachment_dir: Path, metadata_context: dict | None, result_data: dict | None):
    return upsert_bone_age_feedback_csv(
        study_uid,
        attachment_dir,
        metadata_context,
        result_data,
        corrected_data=None,
        review_metadata=None,
    )


def upsert_bone_age_feedback_csv(study_uid: str, attachment_dir: Path, metadata_context: dict | None, result_data: dict | None, corrected_data: dict | None = None, review_metadata: dict | None = None):
    row = build_bone_age_feedback_row(study_uid, metadata_context, result_data)
    corrected_data = corrected_data or {}
    review_metadata = review_metadata or {}

    if "bone_age_years" in corrected_data:
        row["corrected_bone_age_years"] = corrected_data.get("bone_age_years") or ""
    if "bone_age_months" in corrected_data:
        row["corrected_bone_age_months"] = corrected_data.get("bone_age_months") or ""
    if "sex" in corrected_data:
        row["corrected_sex"] = _normalize_sex(corrected_data.get("sex"))

    if review_metadata:
        row["validation_status"] = review_metadata.get("validation_status") or row.get("validation_status", "pending_review")
        row["reviewer_id"] = review_metadata.get("reviewer_id") or ""
        row["correction_notes"] = review_metadata.get("correction_notes") or ""
        row["export_status"] = review_metadata.get("export_status") or row.get("export_status", "local_only")
        row["server_sync_status"] = review_metadata.get("server_sync_status") or row.get("server_sync_status", "not_synced")
        row["review_timestamp"] = review_metadata.get("review_timestamp") or _utc_timestamp()

    path = attachment_dir / "bone_age_feedback.csv"

    rows = _read_csv_rows(path)
    replaced = False
    preserve_existing_human_fields = not (corrected_data or review_metadata)
    for idx, existing in enumerate(rows):
        if (existing.get("case_id") or "") == study_uid:
            rows[idx] = _merge_feedback_row(
                existing,
                row,
                preserve_existing_human_fields=preserve_existing_human_fields,
            )
            replaced = True
            break

    if not replaced:
        rows.append(row)

    field_order = _ordered_fields(rows)
    _write_csv_rows(path, rows, field_order)
    return path


def build_mg_feedback_row(
    study_uid: str,
    source_csv_path: str,
    row_data: dict,
    *,
    selected_box,
    corrected_status: str,
    corrected_classification,
    mammography_fields: dict | None = None,
):
    mammography_fields = mammography_fields or {}
    patient_id = (
        row_data.get("patient_id")
        or row_data.get("patient_uid")
        or row_data.get("PatientID")
        or ""
    )
    study_instance_uid = (
        row_data.get("study_instance_uid")
        or row_data.get("study_uid")
        or row_data.get("StudyInstanceUID")
        or study_uid
    )
    series_instance_uid = (
        row_data.get("series_instance_uid")
        or row_data.get("series_uid")
        or row_data.get("SeriesInstanceUID")
        or ""
    )
    sop_instance_uid = (
        row_data.get("sop_instance_uid")
        or row_data.get("SOPInstanceUID")
        or ""
    )
    dicom_full_path = row_data.get("dicom_full_path") or row_data.get("dicom_path") or row_data.get("path") or ""
    source_row_key = mammography_fields.get("source_row_key") or dicom_full_path
    selected_box_str = "" if not selected_box else str([float(v) for v in selected_box])

    corrected_classification_str = ""
    if isinstance(corrected_classification, (list, tuple)):
        corrected_classification_str = "|".join(str(v).strip() for v in corrected_classification if str(v).strip())
    elif corrected_classification is not None:
        corrected_classification_str = str(corrected_classification).strip()

    ai_classification = (
        row_data.get("labels_pred")
        or row_data.get("label")
        or row_data.get("class")
        or ""
    )
    ai_confidence = (
        row_data.get("scores")
        or row_data.get("score")
        or row_data.get("confidence")
        or row_data.get("conf")
        or ""
    )
    requested_finding_uid = mammography_fields.get("finding_uid")
    record_id = (
        mammography_fields.get("record_id")
        or (requested_finding_uid if requested_finding_uid and not selected_box_str else None)
        or f"{study_uid}:{dicom_full_path}:{selected_box_str}"
    )
    finding_uid = requested_finding_uid or record_id

    return {
        "schema": "eagleeye_feedback_v1",
        "schema_version": 1,
        "case_id": study_uid,
        "record_id": record_id,
        "finding_uid": finding_uid,
        "patient_id": patient_id,
        "study_instance_uid": study_instance_uid,
        "series_instance_uid": series_instance_uid,
        "sop_instance_uid": sop_instance_uid,
        "module_name": "mammography",
        "modality": "MG",
        "source_csv": source_csv_path,
        "source_row_key": source_row_key,
        "source_row_index": mammography_fields.get("source_row_index", ""),
        "source_box_index": mammography_fields.get("source_box_index", ""),
        "source_kind": mammography_fields.get("source_kind", ""),
        "ai_box": selected_box_str,
        "ai_classification": ai_classification,
        "ai_confidence": ai_confidence,
        "ai_laterality": _pick(row_data, ["laterality", "side", "breast_side", "Laterality"]),
        "ai_view": _pick(row_data, ["view", "image_view", "ViewPosition", "view_position"]),
        "ai_lesion_type": _pick(row_data, ["lesion_type", "finding_type", "labels_pred", "label", "class"]),
        "ai_location": _pick(row_data, ["location", "breast_location"]),
        "ai_quadrant": _pick(row_data, ["quadrant"]),
        "ai_clock_position": _pick(row_data, ["clock_position", "clock"]),
        "ai_depth": _pick(row_data, ["depth"]),
        "ai_birads_category": _pick(row_data, ["birads", "bi_rads", "birads_category"]),
        "corrected_box": selected_box_str if corrected_status == "abnormal" else "",
        "corrected_classification": corrected_classification_str,
        "corrected_status": corrected_status,
        "corrected_laterality": mammography_fields.get("laterality", ""),
        "corrected_view": mammography_fields.get("view", ""),
        "corrected_lesion_type": mammography_fields.get("lesion_type", ""),
        "corrected_location": mammography_fields.get("location", ""),
        "corrected_quadrant": mammography_fields.get("quadrant", ""),
        "corrected_clock_position": mammography_fields.get("clock_position", ""),
        "corrected_depth": mammography_fields.get("depth", ""),
        "corrected_birads_category": mammography_fields.get("birads_category", ""),
        "corrected_confidence": mammography_fields.get("confidence", ""),
        "polygon_ijk_points": mammography_fields.get("polygon_ijk_points", ""),
        "polygon_world_points": mammography_fields.get("polygon_world_points", ""),
        "human_action": mammography_fields.get("human_action", "update"),
        "validation_status": "reviewed",
        "reviewer_id": "",
        "review_timestamp": "",
        "correction_notes": "",
        "export_status": "local_only",
        "server_sync_status": "not_synced",
    }


def write_mg_feedback_csv(
    study_uid: str,
    attachment_dir: Path,
    source_csv_path: str,
    row_data: dict,
    *,
    selected_box,
    corrected_status: str,
    corrected_classification,
    review_metadata: dict | None = None,
    mammography_fields: dict | None = None,
):
    row = build_mg_feedback_row(
        study_uid,
        source_csv_path,
        row_data,
        selected_box=selected_box,
        corrected_status=corrected_status,
        corrected_classification=corrected_classification,
        mammography_fields=mammography_fields,
    )
    review_metadata = review_metadata or {}
    if review_metadata:
        row["validation_status"] = review_metadata.get("validation_status") or row.get("validation_status", "reviewed")
        row["reviewer_id"] = review_metadata.get("reviewer_id") or ""
        row["correction_notes"] = review_metadata.get("correction_notes") or ""
        row["export_status"] = review_metadata.get("export_status") or row.get("export_status", "local_only")
        row["server_sync_status"] = review_metadata.get("server_sync_status") or row.get("server_sync_status", "not_synced")
        row["review_timestamp"] = review_metadata.get("review_timestamp") or _utc_timestamp()

    path = attachment_dir / "mg_feedback.csv"

    rows = _read_csv_rows(path)
    replaced = False
    for idx, existing in enumerate(rows):
        if (existing.get("record_id") or "") == row["record_id"]:
            rows[idx] = _merge_feedback_row(
                existing,
                row,
                preserve_existing_human_fields=False,
            )
            replaced = True
            break

    if not replaced:
        rows.append(row)

    field_order = _ordered_fields(rows)
    _write_csv_rows(path, rows, field_order)
    return path
