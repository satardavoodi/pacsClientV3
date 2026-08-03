"""Guard: OPT-46 — crash-durable download-queue persistence (disk task-specs).

The DM queue (PENDING/FAILED/priority) lived only in memory → lost on a crash. OPT-46 persists each
enqueued study's minimal re-enqueue spec to ``<study_dir>/.dm_task.json`` (DISK, not the DB → no
interaction with OPT-45), and on startup re-feeds the still-incomplete specs to the SAME
``add_downloads`` path so interrupted downloads auto-resume (deduped vs the disk resume). Flag-gated
DEFAULT-OFF (``AIPACS_DM_QUEUE_PERSIST=1``). Pure stdlib helper → fully offscreen-testable.
"""
import importlib
import os
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "modules" / "download_manager").is_dir() and (anc / "database").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _qp():
    try:
        return importlib.import_module("modules.download_manager.state.queue_persistence")
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"queue_persistence import unavailable: {exc}")


@pytest.fixture(autouse=True)
def _clean_env():
    saved = os.environ.get("AIPACS_DM_QUEUE_PERSIST")
    os.environ.pop("AIPACS_DM_QUEUE_PERSIST", None)
    yield
    os.environ.pop("AIPACS_DM_QUEUE_PERSIST", None)
    if saved is not None:
        os.environ["AIPACS_DM_QUEUE_PERSIST"] = saved


def _study(uid="1.2.3", n1=3, n2=2):
    return {
        "study_uid": uid, "patient_id": "P1", "patient_name": "DOE^JOHN",
        "modality": "CT", "study_date": "20260728",
        "series": [
            {"series_uid": "1.2.3.1", "series_number": "2", "image_count": n1,
             "series_description": "AX", "thumbnail_data": b"\x00\x01", "thumbnail_path": "x.png"},
            {"series_uid": "1.2.3.2", "series_number": "3", "image_count": n2,
             "series_description": "COR", "thumbnail_data": b"\xff"},
        ],
    }


def _put_dcms(study_dir: Path, per_series: dict):
    for sn, count in per_series.items():
        d = study_dir / str(sn)
        d.mkdir(parents=True, exist_ok=True)
        for i in range(count):
            (d / f"Instance_{i:04d}.dcm").write_bytes(b"\x00" * 8)


# ── flag gating ──

def test_flag_default_off_is_noop(tmp_path):
    m = _qp()
    assert m.queue_persist_enabled() is False
    assert m.persist_task_spec(str(tmp_path / "1.2.3"), _study()) is False
    assert not (tmp_path / "1.2.3" / ".dm_task.json").exists()
    assert m.scan_incomplete_task_specs(str(tmp_path)) == []


# ── sanitisation ──

def test_sanitize_drops_bytes_keeps_reenqueue_fields():
    m = _qp()
    spec = m.sanitize_study_spec(_study())
    assert spec["study_uid"] == "1.2.3" and spec["patient_name"] == "DOE^JOHN"
    assert len(spec["series"]) == 2
    for s in spec["series"]:
        assert s.get("series_uid")
        assert "thumbnail_data" not in s and "thumbnail_path" not in s  # never persist bytes


# ── persist + scan round-trip ──

def test_persist_then_scan_returns_incomplete(tmp_path):
    m = _qp()
    os.environ["AIPACS_DM_QUEUE_PERSIST"] = "1"
    study_dir = tmp_path / "1.2.3"
    assert m.persist_task_spec(str(study_dir), _study(n1=3, n2=2)) is True
    assert (study_dir / ".dm_task.json").exists()
    assert not list(study_dir.glob("*.part"))  # atomic — no torn temp left
    # 0 images on disk → incomplete → returned for re-enqueue
    specs = m.scan_incomplete_task_specs(str(tmp_path))
    assert len(specs) == 1 and specs[0]["study_uid"] == "1.2.3"


def test_scan_deletes_and_skips_complete_study(tmp_path):
    m = _qp()
    os.environ["AIPACS_DM_QUEUE_PERSIST"] = "1"
    study_dir = tmp_path / "1.2.3"
    m.persist_task_spec(str(study_dir), _study(n1=3, n2=2))   # expected = 5
    _put_dcms(study_dir, {"2": 3, "3": 2})                     # disk = 5 → complete
    specs = m.scan_incomplete_task_specs(str(tmp_path))
    assert specs == []                                         # not re-enqueued
    assert not (study_dir / ".dm_task.json").exists()          # self-cleaned


def test_partial_study_is_reenqueued_not_cleaned(tmp_path):
    m = _qp()
    os.environ["AIPACS_DM_QUEUE_PERSIST"] = "1"
    study_dir = tmp_path / "1.2.3"
    m.persist_task_spec(str(study_dir), _study(n1=3, n2=2))   # expected = 5
    _put_dcms(study_dir, {"2": 1})                             # disk = 1 → incomplete
    specs = m.scan_incomplete_task_specs(str(tmp_path))
    assert len(specs) == 1
    assert (study_dir / ".dm_task.json").exists()             # kept for the resume


def test_persist_requires_a_series_list(tmp_path):
    m = _qp()
    os.environ["AIPACS_DM_QUEUE_PERSIST"] = "1"
    no_series = {"study_uid": "1.2.9", "patient_name": "X", "series": []}
    assert m.persist_task_spec(str(tmp_path / "1.2.9"), no_series) is False


def test_unknown_expected_count_is_never_marked_complete(tmp_path):
    # a spec whose series carry no image_count (expected=0) must NOT be treated as complete,
    # even with files on disk — it is re-enqueued so the normal resume logic decides.
    m = _qp()
    os.environ["AIPACS_DM_QUEUE_PERSIST"] = "1"
    study_dir = tmp_path / "1.2.7"
    spec = {"study_uid": "1.2.7", "patient_name": "X",
            "series": [{"series_uid": "s1", "series_number": "1"}]}
    m.persist_task_spec(str(study_dir), spec)
    _put_dcms(study_dir, {"1": 4})
    assert m.study_complete_on_disk(str(study_dir), m.sanitize_study_spec(spec)) is False
    assert len(m.scan_incomplete_task_specs(str(tmp_path))) == 1


# ── wiring source pins ──

def test_wired_into_add_downloads_and_restore():
    root = _repo_root()
    q = (root / "modules" / "download_manager" / "ui" / "widget" / "_dm_queue.py").read_text("utf-8")
    assert "persist_task_spec" in q and "def _restore_persisted_queue" in q
    assert "start_immediately=False" in q  # restore must not force-start; use normal rules
    w = (root / "modules" / "download_manager" / "ui" / "widget" / "widget.py").read_text("utf-8")
    assert "_restore_persisted_queue" in w and "queue_persist_enabled" in w
