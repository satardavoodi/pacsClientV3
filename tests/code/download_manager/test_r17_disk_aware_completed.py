"""R17 stale-COMPLETED hardening (46640/46533, 2026-06-15).

R17b (DB check) already verifies files on disk before trusting a 'Completed'
status; R17a (in-memory StateStore) blanket-blocked any COMPLETED study, so a
study that GREW on the server (or whose files were cleared) was rejected and its
new series never downloaded. R17a now mirrors R17b: a COMPLETED study whose files
are missing on disk is allowed to RESUME (download the missing series); a
genuinely-complete study still blocks. Gated by AIPACS_R17_DISK_AWARE_COMPLETED.

Uses fakes (state store + task) so no real download manager / server is needed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from modules.download_manager.rules import validation_rules as vr
from modules.download_manager.core.enums import DownloadStatus


class _FakeStore:
    def __init__(self, state=None):
        self._state = state

    def exists(self, uid):
        return self._state is not None

    def get(self, uid):
        return self._state


def _series(num, count):
    return SimpleNamespace(series_number=num, image_count=count)


def _task(output_dir=None, series_list=None, study_uid="1.2.3"):
    return SimpleNamespace(
        study_uid=study_uid, output_dir=output_dir,
        series_list=series_list or [], validate=lambda: None,
    )


def _rules(state=None):
    return vr.ValidationRules(state_store=_FakeStore(state), config={})


def _mk_series_dir(study_dir, num, n_dcm):
    d = study_dir / str(num)
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n_dcm):
        (d / f"{i}.dcm").write_bytes(b"x")
    return d


# ── the disk-completeness helper ──────────────────────────────────────────────
def test_files_complete_true_when_all_present(tmp_path):
    study = tmp_path / "1.2.3"
    _mk_series_dir(study, 1, 3)
    _mk_series_dir(study, 2, 2)
    t = _task(str(study), [_series(1, 3), _series(2, 2)])
    assert _rules()._task_files_complete_on_disk(t) is True


def test_files_complete_false_when_a_series_is_missing(tmp_path):
    study = tmp_path / "1.2.3"
    _mk_series_dir(study, 1, 3)  # series 2 never created
    t = _task(str(study), [_series(1, 3), _series(2, 2)])
    assert _rules()._task_files_complete_on_disk(t) is False


def test_files_complete_false_when_partial(tmp_path):
    study = tmp_path / "1.2.3"
    _mk_series_dir(study, 1, 1)  # 1 of 3
    t = _task(str(study), [_series(1, 3)])
    assert _rules()._task_files_complete_on_disk(t) is False


def test_files_complete_true_when_nothing_to_verify():
    assert _rules()._task_files_complete_on_disk(_task(None, [])) is True


# ── the R17a decision ─────────────────────────────────────────────────────────
def test_completed_but_files_missing_resumes(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "_R17_DISK_AWARE_COMPLETED", True, raising=False)
    study = tmp_path / "1.2.3"
    _mk_series_dir(study, 1, 1)  # series 2 (the new one) missing
    t = _task(str(study), [_series(1, 1), _series(2, 5)])
    res = _rules(SimpleNamespace(status=DownloadStatus.COMPLETED)).validate_download_task(t)
    assert res.allowed is False
    assert res.action == "resume"
    assert res.metadata.get("should_resume") is True


def test_completed_and_genuinely_complete_blocks(tmp_path):
    study = tmp_path / "1.2.3"
    _mk_series_dir(study, 1, 3)
    t = _task(str(study), [_series(1, 3)])
    res = _rules(SimpleNamespace(status=DownloadStatus.COMPLETED)).validate_download_task(t)
    assert res.allowed is False
    assert res.action == "skip"


def test_cancelled_always_blocks_even_if_files_missing(tmp_path):
    study = tmp_path / "1.2.3"  # no files at all
    t = _task(str(study), [_series(1, 5)])
    res = _rules(SimpleNamespace(status=DownloadStatus.CANCELLED)).validate_download_task(t)
    assert res.allowed is False
    assert res.action == "skip"


def test_flag_off_completed_always_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "_R17_DISK_AWARE_COMPLETED", False, raising=False)
    study = tmp_path / "1.2.3"  # files missing -> would resume if flag on
    t = _task(str(study), [_series(1, 5)])
    res = _rules(SimpleNamespace(status=DownloadStatus.COMPLETED)).validate_download_task(t)
    assert res.allowed is False
    assert res.action == "skip"  # legacy blanket block preserved
