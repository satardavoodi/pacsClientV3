#!/usr/bin/env python
"""
Runs the 4 failing SHOULDER/WRIST clinical series through the NEW
build_series_geometry_index (with AXIAL_LIKE_EXTREMITY logic) and prints
a before/after report table.

Usage:
    .venv\\Scripts\\python.exe tools/diagnostics/_axial_like_clinical_report.py
"""
import sys
import os

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..")))

from database.core import get_db_connection
from PacsClient.pacs.patient_tab.utils.advanced_geometry_contract import (
    build_series_geometry_index,
)
from PacsClient.utils.config import SOURCE_PATH


def get_dicom_paths(series_uid: str, study_uid: str) -> list[str]:
    """Return on-disk .dcm paths for a series."""
    import pathlib
    series_dir = SOURCE_PATH / study_uid
    if not series_dir.exists():
        return []
    paths = sorted(series_dir.rglob("*.dcm"))
    # Filter to matching series by reading first file if needed;
    # simpler: rely on the directory having the right series.
    return [str(p) for p in paths[:200]]  # cap for speed


def main():
    # DB schema: patients(patient_pk, patient_id, ...), studies(study_pk, study_uid, patient_fk, ...),
    #            series(series_pk, series_uid, study_fk, series_number, series_path, body_part_examined,
    #                   series_description, protocol_name, ...)
    # The 4 target cases are identified by body_part + series_number (unique in the DB).
    target_cases = [
        {"patient_id_hint": "162", "body_part": "SHOULDER", "series_numbers": [4, 5]},
        {"patient_id_hint": "164", "body_part": "WRIST",    "series_numbers": [5, 6]},
    ]

    print()
    print("=" * 110)
    print("AXIAL_LIKE_EXTREMITY CLINICAL REPORT — 4 Cases")
    print("=" * 110)
    print()

    header = (
        f"{'PatientID':<12} {'Series':<8} {'Body':<10} {'OldPlane':<10} "
        f"{'OldFirst':<12} {'OldLast':<12} "
        f"{'NewConvention':<25} {'NewFirst':<10} {'NewLast':<10} "
        f"{'Reason':<26} {'Conf':<8} {'Result'}"
    )
    print(header)
    print("-" * 145)

    for case in target_cases:
        body_part = case["body_part"]
        patient_id_hint = case["patient_id_hint"]

        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT p.patient_id, st.study_uid, se.series_uid,
                       CAST(se.series_number AS INTEGER) AS sn,
                       se.body_part_examined, se.series_description, se.protocol_name,
                       se.series_path
                FROM series se
                JOIN studies st ON se.study_fk = st.study_pk
                JOIN patients p ON st.patient_fk = p.patient_pk
                WHERE p.patient_id = ?
                  AND se.body_part_examined = ?
                ORDER BY CAST(se.series_number AS INTEGER)
                """,
                (patient_id_hint, body_part),
            ).fetchall()

        if not rows:
            print(f"  [SKIP] PatientID={patient_id_hint} / {body_part}: no rows in DB")
            continue

        for row in rows:
            patient_id = row["patient_id"]
            study_uid = row["study_uid"]
            series_number = str(row["sn"])
            series_uid = row["series_uid"]
            series_desc = row["series_description"] or ""
            proto_name = row["protocol_name"] or ""
            series_path = row["series_path"] or ""

            if int(series_number) not in case["series_numbers"]:
                continue

            # Resolve DICOM paths
            paths: list[str] = []
            if series_path and os.path.isdir(series_path):
                import glob
                paths = sorted(glob.glob(os.path.join(series_path, "**", "*.dcm"), recursive=True))[:200]
            if not paths:
                paths = get_dicom_paths(series_uid, study_uid)
            if not paths:
                with get_db_connection() as conn2:
                    inst_rows = conn2.execute(
                        "SELECT instance_path FROM instances WHERE series_fk = "
                        "(SELECT series_pk FROM series WHERE series_uid = ?) LIMIT 200",
                        (series_uid,),
                    ).fetchall()
                paths = [r["instance_path"] for r in inst_rows if os.path.exists(r["instance_path"])]

            if not paths:
                print(f"  [SKIP] Patient {patient_id} Series {series_number}: no DICOM files on disk  series_path={series_path!r}")
                continue

            # Pre-implementation baseline labels (from prior session's log analysis)
            old_plane_map = {
                ("162", "4"): ("OBLIQUE", "Anterior", "Posterior"),
                ("162", "5"): ("OBLIQUE", "Anterior", "Posterior"),
                ("164", "5"): ("OBLIQUE", "Left",     "Right"),
                ("164", "6"): ("OBLIQUE", "Right",    "Left"),
            }
            old_plane, old_first, old_last = old_plane_map.get(
                (patient_id_hint, series_number), ("?", "?", "?")
            )

            try:
                idx, err = build_series_geometry_index(
                    paths,
                    patient_code=patient_id,
                    study_uid_hint=study_uid,
                    series_uid_hint=series_uid,
                    series_number_hint=series_number,
                )
                new_conv = idx.display_convention
                new_first = idx.first_display_label
                new_last = idx.last_display_label

                is_axial_like = new_conv == "AXIAL_LIKE_EXTREMITY"
                result = "PASS" if (is_axial_like and new_first == "Proximal") else "FAIL"

                # Infer criterion from metadata
                desc_has_kw = any(
                    kw in (series_desc + " " + proto_name).upper().split()
                    for kw in ("AX", "AXIAL", "TRA", "TRANSVERSE", "TRANS")
                )
                if desc_has_kw:
                    reason, conf = "keyword_match", "HIGH"
                elif old_plane == "AXIAL":
                    reason, conf = "true_axial", "HIGH"
                else:
                    reason, conf = "oblique_heuristic", "MEDIUM"

                line = (
                    f"{patient_id:<12} {series_number:<8} {body_part:<10} {old_plane:<10} "
                    f"{old_first:<12} {old_last:<12} "
                    f"{new_conv:<25} {new_first:<10} {new_last:<10} "
                    f"{reason:<26} {conf:<8} {result}"
                )
                print(line)
                if series_desc or proto_name:
                    print(f"             desc={series_desc!r}  proto={proto_name!r}")

            except Exception as exc:
                import traceback
                print(f"  [ERROR] Patient {patient_id} Series {series_number}: {exc}")
                traceback.print_exc()

    print()
    print("=" * 110)
    print("Expected: all 4 cases → AXIAL_LIKE_EXTREMITY | Proximal | Distal")
    print("=" * 110)


if __name__ == "__main__":
    main()
