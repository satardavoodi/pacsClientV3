from __future__ import annotations

import sqlite3
from pathlib import Path

import modules.printing.data.dicom_enrichment as enrichment
import modules.printing.data.series_repository as repo


def _create_schema(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE studies (
            study_pk INTEGER PRIMARY KEY AUTOINCREMENT,
            study_uid TEXT UNIQUE
        );

        CREATE TABLE series (
            series_pk INTEGER PRIMARY KEY AUTOINCREMENT,
            series_uid TEXT UNIQUE,
            study_fk INTEGER NOT NULL,
            series_name TEXT,
            series_number INTEGER,
            series_description TEXT,
            modality TEXT,
            image_count INTEGER DEFAULT 0,
            thumbnail_path TEXT,
            series_path TEXT,
            protocol_name TEXT,
            body_part_examined TEXT,
            manufacturer TEXT,
            institution_name TEXT
        );

        CREATE TABLE instances (
            instance_pk INTEGER PRIMARY KEY AUTOINCREMENT,
            series_fk INTEGER NOT NULL,
            instance_path TEXT,
            instance_number INTEGER
        );
        """
    )
    conn.commit()
    conn.close()


def test_get_series_for_study_returns_ordered_records(tmp_path, monkeypatch):
    db_path = tmp_path / "dicom.db"
    _create_schema(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO studies (study_uid) VALUES (?)", ("study-1",))
    conn.execute(
        """
        INSERT INTO series (
            series_uid, study_fk, series_name, series_number, series_description, modality, image_count
        ) VALUES (?, 1, ?, ?, ?, ?, ?)
        """,
        ("series-2", "second", 2, "Second", "CT", 10),
    )
    conn.execute(
        """
        INSERT INTO series (
            series_uid, study_fk, series_name, series_number, series_description, modality, image_count
        ) VALUES (?, 1, ?, ?, ?, ?, ?)
        """,
        ("series-1", "first", 1, "First", "MR", 20),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(repo, "_resolve_db_path", lambda: db_path)

    series = repo.get_series_for_study("study-1")

    assert [item["series_uid"] for item in series] == ["series-1", "series-2"]


def test_get_dicom_paths_for_series_prefers_instance_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "dicom.db"
    _create_schema(db_path)

    series_dir = tmp_path / "study" / "series-a"
    series_dir.mkdir(parents=True)
    image1 = series_dir / "002.dcm"
    image2 = series_dir / "001.dcm"
    image1.write_text("a", encoding="utf-8")
    image2.write_text("b", encoding="utf-8")

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO studies (study_uid) VALUES (?)", ("study-1",))
    conn.execute(
        """
        INSERT INTO series (
            series_uid, study_fk, series_name, series_number, series_description, modality, image_count, series_path
        ) VALUES (?, 1, ?, ?, ?, ?, ?, ?)
        """,
        ("series-1", "first", 1, "First", "CT", 2, str(series_dir)),
    )
    conn.execute(
        "INSERT INTO instances (series_fk, instance_path, instance_number) VALUES (1, ?, 2)",
        (str(image1),),
    )
    conn.execute(
        "INSERT INTO instances (series_fk, instance_path, instance_number) VALUES (1, ?, 1)",
        (str(image2),),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(repo, "_resolve_db_path", lambda: db_path)

    paths = repo.get_dicom_paths_for_series(1)

    assert paths == [str(image2), str(image1)]


def test_get_series_with_enrichment_backfills_missing_counts(tmp_path, monkeypatch):
    db_path = tmp_path / "dicom.db"
    _create_schema(db_path)

    series_dir = tmp_path / "study" / "series-b"
    series_dir.mkdir(parents=True)
    image = series_dir / "001.dcm"
    image.write_text("pixel-data", encoding="utf-8")

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO studies (study_uid) VALUES (?)", ("study-1",))
    conn.execute(
        """
        INSERT INTO series (
            series_uid, study_fk, series_name, series_number, series_description, modality, image_count, series_path
        ) VALUES (?, 1, ?, ?, ?, ?, ?, ?)
        """,
        ("series-1", "first", 1, "First", "CT", 0, str(series_dir)),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(repo, "_resolve_db_path", lambda: db_path)

    series = enrichment.get_series_with_enrichment("study-1")

    assert len(series) == 1
    assert series[0]["image_count"] == 1
    assert series[0]["series_path"] == str(series_dir)
