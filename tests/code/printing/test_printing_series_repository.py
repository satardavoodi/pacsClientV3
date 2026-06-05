"""Specs for modules.printing.data.series_repository / dicom_enrichment.

Spec refresh 2026-06-04 (RELIABILITY_STABILITY_REVIEW §13): the repository was
rewritten from a private sqlite path (`_resolve_db_path` + raw connection)
onto the CENTRAL `database.manager` API, so the old tests failed at
`monkeypatch.setattr(repo, "_resolve_db_path", ...)` (AttributeError) — which
fortuitously also protected the live `dicom.db` from being hit. These tests
now fake the `database.manager` functions the repository calls (the manager's
own SQL — e.g. `ORDER BY series_number` — is its contract, covered at its own
layer), and patch `DICOM_IMAGES_DIR` for the on-disk series resolution. No
sqlite database is touched at all, honoring the DB test-isolation invariant.
"""
from __future__ import annotations

from pathlib import Path

import database.manager as db_manager
import PacsClient.utils.data_paths as data_paths
import modules.printing.data.dicom_enrichment as enrichment
import modules.printing.data.series_repository as repo


def _series_row(series_pk, series_uid, series_number, description, modality,
                image_count):
    """Shape returned by database.manager.get_series_by_study_pk (dict rows)."""
    return {
        "series_pk": series_pk,
        "series_uid": series_uid,
        "series_number": series_number,
        "series_description": description,
        "modality": modality,
        "image_count": image_count,
        "thumbnail_path": None,
    }


def test_get_series_for_study_returns_ordered_records(monkeypatch):
    monkeypatch.setattr(db_manager, "find_study_pk_with_study_uid",
                        lambda uid: 1 if uid == "study-1" else None)
    # The manager contract orders by series_number (ORDER BY in its SQL).
    monkeypatch.setattr(db_manager, "get_series_by_study_pk", lambda pk: [
        _series_row(11, "series-1", 1, "First", "MR", 20),
        _series_row(12, "series-2", 2, "Second", "CT", 10),
    ])

    series = repo.get_series_for_study("study-1")

    assert [item["series_uid"] for item in series] == ["series-1", "series-2"]
    assert series[0]["modality"] == "MR"
    assert series[0]["image_count"] == 20
    assert series[1]["series_description"] == "Second"
    assert all(item["study_uid"] == "study-1" for item in series)


def test_get_series_for_study_unknown_study_returns_empty(monkeypatch):
    monkeypatch.setattr(db_manager, "find_study_pk_with_study_uid",
                        lambda uid: None)
    assert repo.get_series_for_study("missing") == []


def test_get_dicom_paths_for_series_prefers_instance_rows(tmp_path, monkeypatch):
    series_dir = tmp_path / "study" / "series-a"
    series_dir.mkdir(parents=True)
    image1 = series_dir / "002.dcm"
    image2 = series_dir / "001.dcm"
    image1.write_text("a", encoding="utf-8")
    image2.write_text("b", encoding="utf-8")

    def fake_instances(series_pk, group_id=0):
        assert series_pk == 1
        if group_id == 0:
            return [
                {"instance_path": str(image1), "instance_number": 2},
                {"instance_path": str(image2), "instance_number": 1},
            ]
        return []

    monkeypatch.setattr(db_manager, "get_instances_by_series_pk", fake_instances)

    paths = repo.get_dicom_paths_for_series(1)

    # natsorted: 001.dcm before 002.dcm even though rows arrived reversed.
    assert paths == [str(image2), str(image1)]


def test_get_dicom_paths_falls_back_to_disk_scan(tmp_path, monkeypatch):
    # DB has nothing for either group → strategy 2 scans the resolved dir.
    monkeypatch.setattr(db_manager, "get_instances_by_series_pk",
                        lambda series_pk, group_id=0: [])
    series_dir = tmp_path / "study-1" / "Series_1"
    series_dir.mkdir(parents=True)
    (series_dir / "001.dcm").write_text("x", encoding="utf-8")
    monkeypatch.setattr(data_paths, "DICOM_IMAGES_DIR", tmp_path, raising=False)

    paths = repo.get_dicom_paths_for_series(1, study_uid="study-1", series_number=1)

    assert paths == [str(series_dir / "001.dcm")]


def test_get_series_with_enrichment_backfills_missing_counts(tmp_path, monkeypatch):
    # Series row reports image_count=0; one real file exists on disk at the
    # DICOM_IMAGES_DIR/<study_uid>/Series_<n> layout → enrichment backfills 1.
    series_dir = tmp_path / "study-1" / "Series_1"
    series_dir.mkdir(parents=True)
    (series_dir / "001.dcm").write_text("pixel-data", encoding="utf-8")

    monkeypatch.setattr(db_manager, "find_study_pk_with_study_uid",
                        lambda uid: 1)
    monkeypatch.setattr(db_manager, "get_series_by_study_pk", lambda pk: [
        _series_row(11, "series-1", 1, "First", "CT", 0),
    ])
    monkeypatch.setattr(data_paths, "DICOM_IMAGES_DIR", tmp_path, raising=False)

    series = enrichment.get_series_with_enrichment("study-1")

    assert len(series) == 1
    assert series[0]["image_count"] == 1
    assert series[0]["series_path"] == str(series_dir)
