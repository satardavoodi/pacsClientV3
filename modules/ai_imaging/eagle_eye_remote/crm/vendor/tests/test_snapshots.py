"""Snapshot compaction must never be able to lose an audit record.

The snapshot tree grows at about 19.3 MB/day and nothing prunes it, on purpose:
a snapshot is the only record of what a moving system looked like when an
answer was given, and re-fetching gives different numbers. So the growth is
solved by storing the same bytes smaller, never by removing any.

Every test here is about that promise rather than about the saving.
"""

from __future__ import annotations

import gzip
import json
import time
from pathlib import Path

import pytest

from reception_crm import snapshots


def write_snapshot(root: Path, name: str, body, *, age_days: float = 0.0) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    if age_days:
        old = time.time() - age_days * 86400
        import os

        os.utime(path, (old, old))
    return path


def test_a_compacted_snapshot_holds_exactly_what_the_original_held(tmp_path):
    body = {"cashierReport": [{"userName": "abaszadeh", "totalCredit": 1803820000}],
            "note": "مبلغ به ریال"}
    write_snapshot(tmp_path, "020154.json", body, age_days=30)

    result = snapshots.compact(tmp_path, older_than_days=14)

    assert result.compacted == 1
    assert result.failed == 0
    with gzip.open(tmp_path / "020154.json.gz", "rt", encoding="utf-8") as handle:
        assert json.load(handle) == body


def test_persian_survives_the_round_trip(tmp_path):
    """The payloads are mostly Persian; an encoding slip would be silent."""
    body = {"modalityName": "ام آر آی", "note": "تخفیف صندوق"}
    write_snapshot(tmp_path, "130822.json", body, age_days=30)

    snapshots.compact(tmp_path, older_than_days=14)

    assert snapshots.read(tmp_path / "130822.json.gz") == body


def test_a_recent_snapshot_is_left_alone(tmp_path):
    """Something written an hour ago may still be under someone's eye."""
    write_snapshot(tmp_path, "today.json", {"a": 1}, age_days=0)

    result = snapshots.compact(tmp_path, older_than_days=14)

    assert result.compacted == 0
    assert result.skipped_recent == 1
    assert (tmp_path / "today.json").exists()


def test_an_unreadable_snapshot_is_never_deleted(tmp_path):
    """Not ours to repair, and definitely not ours to remove."""
    broken = tmp_path / "corrupt.json"
    broken.write_text("{ this is not json", encoding="utf-8")
    old = time.time() - 30 * 86400
    import os

    os.utime(broken, (old, old))

    result = snapshots.compact(tmp_path, older_than_days=14)

    assert result.failed == 1
    assert result.compacted == 0
    assert broken.exists(), "a file we could not read must survive untouched"


def test_a_failed_compaction_leaves_no_half_finished_gz(tmp_path, monkeypatch):
    """A partial compaction must not look like a finished one.

    If the verification read ever disagrees with the original, the original
    stays and the `.gz` goes — otherwise the next run would find a `.gz` beside
    a missing `.json` and conclude the work was done.
    """
    path = write_snapshot(tmp_path, "020154.json", {"a": 1}, age_days=30)

    # `compact_file` reads the original with `json.loads` and verifies the gzip
    # with `json.load`, so patching `load` alone hits exactly the verification
    # read and nothing else.
    monkeypatch.setattr(snapshots.json, "load", lambda handle: {"a": 999})

    ok, _, _ = snapshots.compact_file(path)

    assert ok is False
    assert path.exists(), "the original must survive a failed verification"
    assert not (tmp_path / "020154.json.gz").exists(), "no half-finished artefact"


def test_readers_do_not_need_to_know_whether_a_file_was_compacted(tmp_path):
    """A reader that only knows `.json` stops FINDING files after compaction.

    That failure is silent and reads as "nothing happened that day", so `read()`
    accepts either form — including the pre-compaction path.
    """
    body = {"a": 1}
    path = write_snapshot(tmp_path, "020154.json", body, age_days=30)
    snapshots.compact(tmp_path, older_than_days=14)

    assert not path.exists()
    assert snapshots.read(path) == body, "the OLD path must still resolve"
    assert snapshots.read(tmp_path / "020154.json.gz") == body


def test_a_missing_snapshot_still_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        snapshots.read(tmp_path / "never-existed.json")


def test_the_run_can_be_bounded(tmp_path):
    """A first run over a year of snapshots must not become an hour of disk I/O."""
    for index in range(6):
        write_snapshot(tmp_path, f"{index:06d}.json", {"i": index}, age_days=30)

    result = snapshots.compact(tmp_path, older_than_days=14, limit=2)

    assert result.compacted == 2
    assert len(list(tmp_path.glob("*.json"))) == 4


def test_the_footprint_separates_compacted_from_not(tmp_path):
    write_snapshot(tmp_path, "old.json", {"a": 1}, age_days=30)
    write_snapshot(tmp_path, "new.json", {"a": 1}, age_days=0)
    snapshots.compact(tmp_path, older_than_days=14)

    report = snapshots.footprint(tmp_path)

    assert report["files"] == 2
    assert report["compacted"] == 1
    assert report["uncompacted"] == 1
    assert "never deleted" in report["policy"] or "ever deleted" in report["policy"], (
        "the policy string must state that nothing is deleted"
    )
