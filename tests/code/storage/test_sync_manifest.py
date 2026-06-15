"""Local manifest + local-vs-server sync decision (read-only model, 2026-06-15).

Guards modules/storage/sync_manifest.py — the unified read-model proposed in the
sync/download lifecycle review (§5.1). Disk is the source of truth; DB facts are
injected so the disk + comparison logic is tested with no database. The model must
NEVER write or download.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from modules.storage import sync_manifest as sm


def _mk_series(study_dir: Path, sn, n_dcm, n_part=0):
    d = study_dir / str(sn)
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n_dcm):
        (d / f"{i}.dcm").write_bytes(b"x" * 200)
    for i in range(n_part):
        (d / f"p{i}.dcm.part").write_bytes(b"x")  # partial write, must NOT count
    return d


@pytest.fixture
def paths(tmp_path, monkeypatch):
    src = tmp_path / "patients"
    src.mkdir()
    thumb = tmp_path / "thumbs"
    thumb.mkdir()
    monkeypatch.setattr(sm, "SOURCE_PATH", src)
    monkeypatch.setattr(sm, "THUMBNAIL_PATH", thumb)
    return src, thumb


def test_not_downloaded(paths):
    d = sm.evaluate_sync("1.2.none", db_number_of_series=0, db_series={})
    assert d["state"] == sm.STATE_NOT_DOWNLOADED


def test_downloaded_all_complete(paths):
    src, _ = paths
    study = src / "1.2.dl"
    study.mkdir()
    _mk_series(study, 1, 5)
    _mk_series(study, 2, 3)
    db = {"1": {"image_count": 5}, "2": {"image_count": 3}}
    d = sm.evaluate_sync("1.2.dl", db_number_of_series=2, db_series=db)
    assert d["state"] == sm.STATE_DOWNLOADED
    assert d["manifest"]["disk_series_count"] == 2


def test_partial_when_a_series_is_undercounted(paths):
    src, _ = paths
    study = src / "1.2.p"
    study.mkdir()
    _mk_series(study, 1, 3)  # disk 3 < server/db 5
    db = {"1": {"image_count": 5}}
    d = sm.evaluate_sync("1.2.p", db_number_of_series=1, db_series=db)
    assert d["state"] == sm.STATE_PARTIAL


def test_partial_when_fewer_series_present(paths):
    src, _ = paths
    study = src / "1.2.f"
    study.mkdir()
    _mk_series(study, 1, 5)  # only 1 of 3 series on disk
    d = sm.evaluate_sync("1.2.f", db_number_of_series=3, db_series={"1": {"image_count": 5}})
    assert d["state"] == sm.STATE_PARTIAL


def test_stale_when_db_knows_study_but_files_gone(paths):
    # No study folder on disk, but the DB row says 3 series -> cleared/lost -> Stale.
    d = sm.evaluate_sync("1.2.gone", db_number_of_series=3, db_series={"1": {"image_count": 5}})
    assert d["state"] == sm.STATE_STALE


def test_thumbnail_only(paths):
    _, thumb = paths
    (thumb / "1.2.t").mkdir()
    (thumb / "1.2.t" / "1.png").write_bytes(b"x")  # thumbnail but no DICOM
    d = sm.evaluate_sync("1.2.t", db_number_of_series=1, db_series={"1": {"image_count": 5}})
    assert d["state"] == sm.STATE_THUMBNAIL_ONLY


def test_part_files_are_not_counted(paths):
    src, _ = paths
    study = src / "1.2.part"
    study.mkdir()
    _mk_series(study, 1, 2, n_part=4)  # 2 finished + 4 .part
    m = sm.build_local_manifest("1.2.part", db_number_of_series=1, db_series={"1": {"image_count": 2}})
    assert m["series"]["1"]["disk_instance_count"] == 2
    assert sm.local_state(m) == sm.STATE_DOWNLOADED


def test_evaluate_sync_lists_missing_partial_and_thumbnails(paths):
    src, thumb = paths
    study = src / "1.2.s"
    study.mkdir()
    _mk_series(study, 1, 5)   # complete vs server 5
    _mk_series(study, 2, 2)   # partial vs server 4
    # series 3 is entirely missing on disk
    (thumb / "1.2.s").mkdir()
    (thumb / "1.2.s" / "1.png").write_bytes(b"x")  # only series 1 has a thumbnail
    db = {"1": {"image_count": 5}, "2": {"image_count": 4}}
    server = [
        {"series_number": 1, "image_count": 5},
        {"series_number": 2, "image_count": 4},
        {"series_number": 3, "image_count": 6},
    ]
    d = sm.evaluate_sync("1.2.s", server_series=server, db_number_of_series=3, db_series=db)
    assert d["missing_series"] == ["3"]
    assert d["partial_series"] == ["2"]
    assert "2" in d["missing_thumbnails"]   # disk files but no thumbnail
    assert "1" not in d["missing_thumbnails"]
    assert d["up_to_date"] is False
    assert d["checked_server"] is True


def test_up_to_date_true_when_nothing_missing(paths):
    src, thumb = paths
    study = src / "1.2.ok"
    study.mkdir()
    _mk_series(study, 1, 5)
    (thumb / "1.2.ok").mkdir()
    (thumb / "1.2.ok" / "1.png").write_bytes(b"x")
    d = sm.evaluate_sync(
        "1.2.ok",
        server_series=[{"series_number": 1, "image_count": 5}],
        db_number_of_series=1, db_series={"1": {"image_count": 5}},
    )
    assert d["up_to_date"] is True
    assert d["missing_series"] == [] and d["partial_series"] == [] and d["missing_thumbnails"] == []


def test_model_is_read_only(paths):
    # Building/evaluating a manifest must not create the study folder or any file.
    src, _ = paths
    before = {p.name for p in src.iterdir()}
    sm.evaluate_sync("1.2.readonly", db_number_of_series=2, db_series={"1": {"image_count": 3}})
    after = {p.name for p in src.iterdir()}
    assert before == after  # nothing created on disk


def test_missing_series_sorted_numerically(paths):
    # Series numbers sort numerically (10 after 2), not lexicographically.
    src, _ = paths
    (src / "1.2.sort").mkdir()
    server = [{"series_number": n, "image_count": 1} for n in (2, 10, 1)]
    d = sm.evaluate_sync("1.2.sort", server_series=server, db_number_of_series=3, db_series={})
    assert d["missing_series"] == ["1", "2", "10"]
