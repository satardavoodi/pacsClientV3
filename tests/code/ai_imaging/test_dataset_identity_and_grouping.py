# -*- coding: utf-8 -*-
"""Guard: Eagle Eye dataset identity + grouping.

Defects fixed (2026-07-14, patient 50016):
  * `patient_uid` was SYNTHESISED from patient_id itself
    (`row_out.setdefault("patient_uid", pick(r, ["patient_uid", "patient_id", ...]))`)
    → a column that could only ever duplicate Patient ID. Removed.
  * The identifiers that matter were MISSING:
      - `updated_csv_with_boxes_*.csv` has only `study_id` (a short RIS number,
        e.g. 163245) — no StudyInstanceUID, no SeriesInstanceUID.
      - `classification_*.csv` has `study_instance_uid` but an EMPTY
        `series_instance_uid`.
    Both carry `dicom_full_path`, and the server stores DICOM as
    `.../<patient_id>/<study_uid>/<series_uid>/<file>.dcm`, so the true UIDs are
    recovered from the path (the file itself lives on the SERVER — unreadable here).
  * The viewer was a flat list; it is now grouped Study → CSV → records.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.ai_imaging.ai_module_ui.service_tab.dataset_identity import (  # noqa: E402
    DROPPED_COLUMNS,
    build_record_key,
    group_rows_by_study,
    is_dicom_uid,
    normalize_record,
    normalize_records,
    parse_uids_from_dicom_path,
    study_group_title,
)

STUDY = "2.16.840.1.113669.632.20.20260713.163245771.1.1"
SERIES_A = "2.16.840.1.113669.632.20.20260713.163424983.10012.11"
SERIES_B = "1.2.826.0.1.3680043.8.498.32800637911931126109349848462597555953"
DPATH_A = (r"D:\Program Files\AI_PACS_SERVER\data\dicom_data\50016"
           rf"\{STUDY}\{SERIES_A}\IMG-68306.dcm")
DPATH_B = (r"D:\Program Files\AI_PACS_SERVER\data\dicom_data\50016"
           rf"\{STUDY}\{SERIES_B}\DOC-0001.dcm")


# ---------------------------------------------------------------------------
# 1. UID recognition + path parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (STUDY, True),
    (SERIES_B, True),
    ("50016", False),        # patient id
    ("163245", False),       # RIS study_id — NOT a StudyInstanceUID
    ("", False),
    (None, False),
    ("abc.def", False),
])
def test_is_dicom_uid(value, expected):
    assert is_dicom_uid(value) is expected


def test_parse_uids_from_the_real_server_path():
    got = parse_uids_from_dicom_path(DPATH_A)
    assert got["patient_id"] == "50016"
    assert got["study_instance_uid"] == STUDY
    assert got["series_instance_uid"] == SERIES_A
    assert got["instance_file"] == "IMG-68306.dcm"


def test_parse_uids_never_guesses_on_a_foreign_path():
    got = parse_uids_from_dicom_path(r"C:\some\random\folder\image.dcm")
    assert got["study_instance_uid"] == ""
    assert got["series_instance_uid"] == ""


# ---------------------------------------------------------------------------
# 2. patient_uid is gone; the real identifiers are filled
# ---------------------------------------------------------------------------

def test_patient_uid_is_dropped():
    assert "patient_uid" in DROPPED_COLUMNS
    row = normalize_record({"patient_id": "50016", "patient_uid": "50016"})
    assert "patient_uid" not in row
    assert row["patient_id"] == "50016"


def test_detection_csv_row_gets_study_and_series_from_the_dicom_path():
    """updated_csv_with_boxes_*.csv: only `study_id`, no UIDs at all."""
    row = normalize_record({
        "study_id": "163245",
        "patient_id": "50016",
        "patient_name": "TORABI^KHADIJE^42Y^^",
        "dicom_full_path": DPATH_B,
        "box": "[]",
        "scores": "[]",
    }, source_csv_file="updated_csv_with_boxes_0.45.csv")

    assert row["study_instance_uid"] == STUDY
    assert row["series_instance_uid"] == SERIES_B
    assert row["patient_id"] == "50016"
    assert row["study_id"] == "163245"           # RIS number preserved, but not as a UID


def test_classification_row_keeps_its_study_uid_and_gains_the_missing_series_uid():
    row = normalize_record({
        "row_index": "0",
        "study_instance_uid": STUDY,
        "series_instance_uid": "",               # empty in the real CSV
        "patient_id": "50016",
        "study_id": "163245",
        "dicom_full_path": DPATH_A,
    }, source_csv_file="classification_0.45.csv")

    assert row["study_instance_uid"] == STUDY
    assert row["series_instance_uid"] == SERIES_A


def test_a_ris_study_id_is_never_promoted_to_a_study_uid():
    row = normalize_record({"study_instance_uid": "163245", "patient_id": "50016"})
    assert row["study_instance_uid"] == ""       # not a UID → not accepted


def test_tab_study_uid_is_the_last_resort_only():
    row = normalize_record({"patient_id": "50016"}, default_study_uid=STUDY)
    assert row["study_instance_uid"] == STUDY

    other = "1.2.3.4.5.6.7"
    row = normalize_record({"dicom_full_path": DPATH_A}, default_study_uid=other)
    assert row["study_instance_uid"] == STUDY, "the row's own path must win over the tab's study"


def test_record_key_uniquely_identifies_each_record():
    base = {"study_instance_uid": STUDY, "series_instance_uid": SERIES_A,
            "dicom_full_path": DPATH_A, "source_csv_file": "classification_0.45.csv"}
    k1 = build_record_key({**base, "row_index": "0"})
    k2 = build_record_key({**base, "row_index": "1"})
    k3 = build_record_key({**base, "row_index": "0",
                           "source_csv_file": "classification_0.44.csv"})
    assert k1 != k2 and k1 != k3
    assert len({k1, k2, k3}) == 3


# ---------------------------------------------------------------------------
# 3. Grouping: Study → CSV → records
# ---------------------------------------------------------------------------

def test_rows_group_under_their_study_then_their_csv():
    rows = normalize_records([
        {"patient_id": "50016", "dicom_full_path": DPATH_A,
         "source_csv_file": "classification_0.45.csv", "row_index": "0"},
        {"patient_id": "50016", "dicom_full_path": DPATH_B,
         "source_csv_file": "classification_0.45.csv", "row_index": "1"},
        {"patient_id": "50016", "dicom_full_path": DPATH_A,
         "source_csv_file": "updated_csv_with_boxes_0.45.csv", "row_index": "0"},
    ])
    groups = group_rows_by_study(rows)

    assert list(groups.keys()) == [STUDY]
    g = groups[STUDY]
    assert list(g["csv_files"].keys()) == ["classification_0.45.csv",
                                           "updated_csv_with_boxes_0.45.csv"]
    assert g["row_count"] == 3
    assert g["patient_ids"] == ["50016"]
    assert sorted(g["series"]) == sorted([SERIES_A, SERIES_B])

    title = study_group_title(g)
    assert STUDY in title and "50016" in title and "2 series" in title and "3 records" in title


def test_unknown_study_is_isolated_not_attributed_to_another_study():
    rows = normalize_records([
        {"patient_id": "50016", "dicom_full_path": DPATH_A, "source_csv_file": "a.csv"},
        {"patient_id": "50016", "source_csv_file": "b.csv"},   # no path, no uid
    ])
    groups = group_rows_by_study(rows)
    assert set(groups.keys()) == {STUDY, ""}
    assert "Unknown study" in study_group_title(groups[""])


# ---------------------------------------------------------------------------
# 4. End-to-end against the REAL CSVs (skipped when not present)
# ---------------------------------------------------------------------------

def test_real_eagle_eye_csvs_now_carry_full_identity():
    from modules.ai_imaging.ai_module_ui.service_tab.dataset_tab import read_dataset_csvs

    attach = (REPO_ROOT / "user_data" / "patients" / "attachments" / STUDY)
    if not attach.is_dir():
        pytest.skip("live attachment folder not present")
    csvs = sorted(attach.glob("*.csv"))
    if not csvs:
        pytest.skip("no CSVs for this study")

    rows = read_dataset_csvs([str(p) for p in csvs], default_study_uid=STUDY)
    assert rows

    assert all("patient_uid" not in r for r in rows), "patient_uid must be gone"
    assert all(r.get("patient_id") for r in rows)
    assert all(r.get("study_instance_uid") == STUDY for r in rows)

    # every row that references a DICOM file must now resolve its series
    with_path = [r for r in rows if r.get("dicom_full_path")]
    assert with_path, "expected rows carrying dicom_full_path"
    assert all(is_dicom_uid(r["series_instance_uid"]) for r in with_path), \
        "series_instance_uid must be recovered from the DICOM path"

    # record keys are unique
    keys = [r["record_key"] for r in rows]
    assert len(keys) == len(set(keys))

    groups = group_rows_by_study(rows)
    assert list(groups.keys()) == [STUDY]
    assert len(groups[STUDY]["csv_files"]) == len(csvs)
