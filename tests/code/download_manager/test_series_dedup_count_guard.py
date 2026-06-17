"""Regression guard: DownloadTask series de-dup prevents IMPOSSIBLE image counts.

Production complaint (patient 46912; earlier 46271): a multi-study patient that is
not yet fully downloaded, with the user rapidly drag-and-dropping series from
different studies into viewports, produced an impossible Download-Manager count —
e.g. 0.2% (622/373322 images) — a total that exists in neither the server nor the
local database. Earlier instance: 423988 images for a 247-image patient.

Root cause: a rapid multi-study drag-preempt enqueue can hand ``DownloadTask`` a
``series_list`` with the SAME series repeated many times; ``total_image_count``
(sum over the list) then balloons. The original guard de-duped by
``series_uid`` ONLY and KEPT every empty-uid row, so repeats that carried no
SeriesInstanceUID (the viewer drag payload) escaped and the count still ballooned.

Fix: de-dup by a COMPOSITE identity — SeriesInstanceUID when present, else
series_number — so empty-uid repeats also collapse. A real study never has two
series sharing a SeriesInstanceUID *or* a series_number, so this is a no-op for
clean tasks and corrects contaminated ones. An implausible total (after de-dup)
is logged as ``[CriticalCountMismatch]``.

``models.py`` is pure-python (no Qt), so these run in any environment. If a
home-panel suite is collected first the known latent ``download_manager`` package
circular-import can block collection — run this file (or the download_manager
suite) first:  ``pytest tests/code/download_manager/test_series_dedup_count_guard.py``
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modules.download_manager.core import models as models  # noqa: E402

SeriesInfo = models.SeriesInfo
DownloadTask = models.DownloadTask


def _series(uid: str = "", number: str = "1", count: int = 100) -> "models.SeriesInfo":
    return SeriesInfo(
        series_uid=uid,
        series_number=number,
        series_description="desc",
        modality="MR",
        image_count=count,
    )


def _task(series_list) -> "models.DownloadTask":
    return DownloadTask(
        study_uid="1.2.3.4",
        patient_id="46912",
        patient_name="SHAHBAZI MARYAM",
        study_date="",
        modality="MR",
        description="",
        series_list=series_list,
    )


def test_duplicate_series_with_uid_collapses():
    t = _task([_series("S1", "1", 100), _series("S1", "1", 100), _series("S2", "2", 50)])
    assert t.series_count == 2
    assert t.total_image_count == 150


def test_duplicate_series_without_uid_collapses_by_number():
    # The 46912 shape: repeated series carrying NO SeriesInstanceUID (drag payload).
    # 5 copies of series 1 (100) + 5 copies of series 2 (50) must collapse to 150,
    # NOT sum to 750. This is the case the original series_uid-only guard missed.
    sl = [_series("", "1", 100) for _ in range(5)] + [_series("", "2", 50) for _ in range(5)]
    t = _task(sl)
    assert t.series_count == 2
    assert t.total_image_count == 150


def test_clean_multi_series_unchanged():
    sl = [_series("S1", "1", 100), _series("S2", "2", 50), _series("S3", "3", 30)]
    t = _task(sl)
    assert t.series_count == 3
    assert t.total_image_count == 180


def test_distinct_uids_same_number_not_collapsed():
    # Defensive: two series with the SAME number but DIFFERENT uids (should never
    # happen inside one real study) are kept separate — identity prefers the uid,
    # so cross-study series are NEVER merged by the number fallback.
    t = _task([_series("A", "1", 100), _series("B", "1", 50)])
    assert t.series_count == 2
    assert t.total_image_count == 150


def test_richer_row_kept_on_collapse():
    # When collapsing, the largest image_count wins (never lose instances).
    t = _task([_series("", "1", 30), _series("", "1", 120)])
    assert t.series_count == 1
    assert t.total_image_count == 120


def test_legacy_flag_keeps_empty_uid_duplicates(monkeypatch):
    # AIPACS_DM_DEDUP_BY_NUMBER=0 restores the old series_uid-only behaviour:
    # empty-uid repeats are NOT collapsed. (_dedupe_series_list reads the module
    # global at call time, so monkeypatching it takes effect for the next task.)
    monkeypatch.setattr(models, "_DM_DEDUP_BY_NUMBER", False)
    t = _task([_series("", "1", 100) for _ in range(3)])
    assert t.series_count == 3
    assert t.total_image_count == 300


def test_critical_count_mismatch_logged(caplog):
    # An implausible per-series count (NOT a duplicate) is flagged as
    # CriticalCountMismatch so the worker/UI can clamp against the manifest.
    with caplog.at_level(logging.ERROR, logger="modules.download_manager.core.models"):
        _task([_series("S1", "1", models._DM_IMPLAUSIBLE_TOTAL_IMAGES + 1)])
    assert "CriticalCountMismatch" in caplog.text


def test_source_wiring_present():
    src = (_REPO_ROOT / "modules/download_manager/core/models.py").read_text(encoding="utf-8")
    assert "_DM_DEDUP_BY_NUMBER" in src
    assert "AIPACS_DM_DEDUP_BY_NUMBER" in src
    assert "CriticalCountMismatch" in src
    # composite identity (uid first, then number fallback)
    assert "'num:'" in src and "'uid:'" in src
