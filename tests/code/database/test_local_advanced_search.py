"""Local Advanced Patient Search regression coverage."""

import pytest


@pytest.fixture()
def local_db(tmp_path, monkeypatch):
    import PacsClient.utils.data_paths as data_paths
    import database._pool as pool

    db_file = tmp_path / "dicom.db"
    monkeypatch.setattr(data_paths, "DATABASE_FILE", str(db_file), raising=False)
    with pool._pool_lock:
        for connections in pool._connection_pool.values():
            for connection in connections:
                try:
                    connection.close()
                except Exception:
                    pass
        pool._connection_pool.clear()

    from database import dicom_db
    dicom_db.init_database()
    yield dicom_db

    with pool._pool_lock:
        for connections in pool._connection_pool.values():
            for connection in connections:
                try:
                    connection.close()
                except Exception:
                    pass
        pool._connection_pool.clear()


def _seed(db):
    rows = [
        ("P1", "ALICE", "042Y", "S1", "2026/01/10", "CT, MR", "CHEST", "Dr Alpha"),
        ("P2", "BOB", "006M", "S2", "20260111", "MR", "BRAIN", "Dr Beta"),
        ("P3", "CAROL", "75", "S3", "20260201", "CT", "CHEST", "Dr Alpha"),
    ]
    with db.get_db_connection() as conn:
        for patient_id, name, age, study_uid, study_date, modality, body_part, physician in rows:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO patients (patient_id, patient_name, age) VALUES (?, ?, ?)",
                (patient_id, name, age),
            )
            patient_pk = cur.lastrowid
            cur.execute(
                "INSERT INTO studies "
                "(study_uid, patient_fk, study_date, modality, body_part, reporting_physician) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (study_uid, patient_pk, study_date, modality, body_part, physician),
            )
        conn.commit()


def test_multiple_patient_ids_and_date_range_are_combined(local_db):
    _seed(local_db)
    rows = local_db.search_patients_local({
        "patient_ids": ["P1", "P3"],
        "date_from": "20260101",
        "date_to": "20260131",
        "modality": "CT",
    })
    assert [row["patient_id"] for row in rows] == ["P1"]


def test_body_part_age_and_physician_filters_work_offline(local_db):
    _seed(local_db)
    rows = local_db.search_patients_local({
        "body_part": "chest",
        "age_min": 40,
        "age_max": 50,
        "physician": "alpha",
    })
    assert [row["patient_id"] for row in rows] == ["P1"]


def test_dicom_month_age_is_converted_to_years(local_db):
    _seed(local_db)
    rows = local_db.search_patients_local({"age_max": 1})
    assert [row["patient_id"] for row in rows] == ["P2"]
