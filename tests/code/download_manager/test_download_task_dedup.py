"""Guard: DownloadTask must de-duplicate its series_list by series_uid (2026-06-14).

Patient 46271 (multi-study) showed a Download Manager total of "31/423988 images"
for a study that really has 247 images. Root cause: an inflated/accumulated
series_list handed to the DownloadTask, so total_image_count (sum over series_list)
ballooned far past the study's real size and the downloader thrashed.

A real study never has two series with the same SeriesInstanceUID, so DownloadTask
now collapses duplicates by series_uid in __post_init__ — a no-op for clean tasks,
a correction for contaminated ones. These tests pin that behaviour.
"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.download_manager.core.models import DownloadTask, SeriesInfo  # noqa: E402


def _series(uid, number, img):
    return SeriesInfo(
        series_uid=uid, series_number=number,
        series_description="s", modality="MR", image_count=img,
    )


def _task(series):
    return DownloadTask(
        study_uid="1.2.3", patient_id="46271", patient_name="KARIMI TAHERE",
        study_date="20260614", modality="MR", description="d", series_list=series,
    )


def test_duplicate_series_collapsed():
    t = _task([_series("a", 1, 22), _series("b", 2, 21),
               _series("a", 1, 22), _series("a", 1, 22)])
    assert t.series_count == 2
    assert t.total_image_count == 43          # 22 + 21, NOT 22*3 + 21
    assert sorted(s.series_uid for s in t.series_list) == ["a", "b"]


def test_clean_list_unchanged():
    t = _task([_series("a", 1, 22), _series("b", 2, 21), _series("c", 3, 10)])
    assert t.series_count == 3
    assert t.total_image_count == 53


def test_duplicate_keeps_max_image_count():
    # same uid, different counts → keep the richer row
    t = _task([_series("a", 1, 5), _series("a", 1, 40)])
    assert t.series_count == 1
    assert t.total_image_count == 40


def test_empty_uid_series_preserved():
    # cannot prove duplication without a uid → keep both
    t = _task([_series("", 1, 5), _series("", 2, 7)])
    assert t.series_count == 2
    assert t.total_image_count == 12


def test_massive_accumulation_collapses_to_real_total():
    # the 46271 class: one series repeated thousands of times
    t = _task([_series("a", 1, 22) for _ in range(2000)] + [_series("b", 2, 21)])
    assert t.series_count == 2
    assert t.total_image_count == 43


def test_post_init_present_in_source():
    src = (_ROOT / "modules/download_manager/core/models.py").read_text(encoding="utf-8")
    assert "_dedupe_series_list" in src
    assert "def __post_init__" in src
    assert "[DM_DEDUP]" in src
