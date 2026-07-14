"""
Eagle Eye dataset — record identity + grouping (PURE: stdlib only, unit-testable).

WHAT WAS WRONG
--------------
The Dataset Viewer showed a `patient_uid` column that was **synthesised** by
`read_dataset_csvs` from `patient_id` itself:

    row_out.setdefault("patient_uid", pick(r, ["patient_uid", "patient_id", ...]))

so it could never be anything other than a duplicate of Patient ID. Meanwhile the
identifiers that actually matter were missing:

  * `updated_csv_with_boxes_*.csv` carries only `study_id` (a short RIS number,
    e.g. 163245) — **no** StudyInstanceUID, **no** SeriesInstanceUID.
  * `classification_*.csv` carries `study_instance_uid` but leaves
    `series_instance_uid` EMPTY.

Both, however, carry `dicom_full_path`, and the server stores DICOM as

    .../dicom_data/<patient_id>/<StudyInstanceUID>/<SeriesInstanceUID>/<file>.dcm

so the real UIDs can be recovered from the path without touching the file (the
path points at the SERVER's disk — we cannot dcmread it from the workstation).

THE RULE
--------
Every record is identified by:  patient_id + study_instance_uid +
series_instance_uid (+ the instance file and the source CSV row for uniqueness
within a series). `patient_uid` is removed — it was never a distinct identifier.
"""

from __future__ import annotations

import os
import re
from collections import OrderedDict
from typing import Dict, Iterable, List, Optional, Tuple

# A DICOM UID is digits + dots. Be strict enough not to mistake a patient id
# (50016) or a study id (163245) for a UID.
_UID_RE = re.compile(r"^\d+(?:\.\d+)+$")

IDENTITY_COLUMNS = (
    "patient_id",
    "study_instance_uid",
    "series_instance_uid",
    "sop_instance_uid",
)

# Columns the viewer must never show again (redundant / misleading).
DROPPED_COLUMNS = ("patient_uid",)


def is_dicom_uid(value) -> bool:
    if value is None:
        return False
    v = str(value).strip()
    return bool(v) and len(v) >= 9 and bool(_UID_RE.match(v))


def parse_uids_from_dicom_path(path) -> Dict[str, str]:
    """Recover patient_id / study UID / series UID / instance file from a DICOM path.

    Server layout: ``.../<patient_id>/<study_uid>/<series_uid>/<file>.dcm``
    Only segments that actually look like DICOM UIDs are used — a path that does
    not follow the layout yields empty strings (never a guess).
    """
    out = {"patient_id": "", "study_instance_uid": "", "series_instance_uid": "",
           "instance_file": ""}
    if not path:
        return out

    norm = str(path).replace("\\", "/")
    parts = [p for p in norm.split("/") if p]
    if not parts:
        return out

    out["instance_file"] = parts[-1]
    dirs = parts[:-1]

    # The two DEEPEST uid-looking directories are study/series (in that order).
    uid_idx = [i for i, seg in enumerate(dirs) if is_dicom_uid(seg)]
    if len(uid_idx) >= 2:
        study_i, series_i = uid_idx[-2], uid_idx[-1]
        out["study_instance_uid"] = dirs[study_i]
        out["series_instance_uid"] = dirs[series_i]
        if study_i - 1 >= 0:
            out["patient_id"] = dirs[study_i - 1]
    elif len(uid_idx) == 1:
        study_i = uid_idx[0]
        out["study_instance_uid"] = dirs[study_i]
        if study_i - 1 >= 0:
            out["patient_id"] = dirs[study_i - 1]
    return out


def _first(row: dict, keys: Iterable[str]) -> str:
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def build_record_key(row: dict) -> str:
    """Stable key that makes every dataset row uniquely addressable."""
    inst = os.path.basename(str(row.get("dicom_full_path", "") or "").replace("\\", "/"))
    return "|".join([
        row.get("study_instance_uid") or "-",
        row.get("series_instance_uid") or "-",
        row.get("sop_instance_uid") or inst or "-",
        row.get("source_csv_file") or "-",
        str(row.get("row_index", "")) or "-",
    ])


def normalize_record(row: dict, *, source_csv_file: str = "",
                     default_study_uid: Optional[str] = None) -> dict:
    """Return the row with canonical identifiers (and `patient_uid` removed).

    Resolution order per identifier:
        explicit CSV column → parsed from `dicom_full_path` → (study only) the
        study the tab is showing. Never invents a value.
    """
    out = dict(row)

    for col in DROPPED_COLUMNS:
        out.pop(col, None)

    if source_csv_file:
        out.setdefault("source_csv_file", source_csv_file)

    dicom_path = _first(out, ("dicom_full_path", "dicom_path", "path", "file", "full_image_path"))
    if dicom_path:
        out.setdefault("dicom_full_path", dicom_path)
    from_path = parse_uids_from_dicom_path(dicom_path)

    patient_id = _first(out, ("patient_id", "PatientID")) or from_path["patient_id"]

    study_uid = _first(out, ("study_instance_uid", "study_uid", "StudyInstanceUID"))
    if not is_dicom_uid(study_uid):
        # e.g. `study_id` = 163245 is a RIS number, NOT a StudyInstanceUID
        study_uid = ""
    study_uid = study_uid or from_path["study_instance_uid"] or (default_study_uid or "")

    series_uid = _first(out, ("series_instance_uid", "series_uid", "SeriesInstanceUID"))
    if not is_dicom_uid(series_uid):
        series_uid = ""
    series_uid = series_uid or from_path["series_instance_uid"]

    sop_uid = _first(out, ("sop_instance_uid", "sop_uid", "SOPInstanceUID"))
    if not is_dicom_uid(sop_uid):
        sop_uid = ""

    out["patient_id"] = patient_id
    out["study_instance_uid"] = study_uid
    out["series_instance_uid"] = series_uid
    out["sop_instance_uid"] = sop_uid
    out["record_key"] = build_record_key(out)
    return out


def normalize_records(rows: Iterable[dict], *,
                      default_study_uid: Optional[str] = None) -> List[dict]:
    return [normalize_record(r, default_study_uid=default_study_uid) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Grouping:  Study Instance UID  →  source CSV  →  rows
# ─────────────────────────────────────────────────────────────────────────────

def group_rows_by_study(rows: List[dict]) -> "OrderedDict[str, dict]":
    """Group flat rows into  study_uid → {csv_file: [rows]}  + per-study summary.

    Rows whose study cannot be identified are grouped under '' (rendered as
    "Unknown study") rather than being dropped or attributed to another study.
    """
    groups: "OrderedDict[str, dict]" = OrderedDict()

    for row in rows:
        study = str(row.get("study_instance_uid") or "")
        csv_name = str(row.get("source_csv_file") or "(unknown csv)")

        g = groups.get(study)
        if g is None:
            g = {
                "study_instance_uid": study,
                "patient_ids": [],
                "patient_names": [],
                "series": [],
                "csv_files": OrderedDict(),
                "row_count": 0,
            }
            groups[study] = g

        rows_for_csv = g["csv_files"].setdefault(csv_name, [])
        rows_for_csv.append(row)
        g["row_count"] += 1

        pid = str(row.get("patient_id") or "")
        if pid and pid not in g["patient_ids"]:
            g["patient_ids"].append(pid)
        pname = str(row.get("patient_name") or "")
        if pname and pname not in g["patient_names"]:
            g["patient_names"].append(pname)
        series = str(row.get("series_instance_uid") or "")
        if series and series not in g["series"]:
            g["series"].append(series)

    return groups


def study_group_title(group: dict) -> str:
    """Human label for a study group node."""
    study = group.get("study_instance_uid") or ""
    head = f"Study {study}" if study else "Unknown study (no StudyInstanceUID)"
    pids = ", ".join(group.get("patient_ids") or []) or "?"
    n_csv = len(group.get("csv_files") or {})
    n_series = len(group.get("series") or [])
    n_rows = group.get("row_count", 0)
    return (f"{head}  ·  Patient {pids}  ·  {n_series} series  ·  "
            f"{n_csv} CSV file{'s' if n_csv != 1 else ''}  ·  {n_rows} record{'s' if n_rows != 1 else ''}")


def csv_group_title(csv_name: str, rows: List[dict]) -> str:
    series = {str(r.get("series_instance_uid") or "") for r in rows}
    series.discard("")
    n = len(rows)
    suffix = f"  ·  {len(series)} series" if series else ""
    return f"{csv_name}  ·  {n} record{'s' if n != 1 else ''}{suffix}"
