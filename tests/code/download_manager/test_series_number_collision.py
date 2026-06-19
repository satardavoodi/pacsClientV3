"""Guards for series-number collision disambiguation (2026-06-19, data loss).

Live finding: a study can contain two genuinely different SeriesInstanceUIDs that
share one series_number (verified: study …86503 had a 24-image and a 156-image
series both numbered 203). The download disk layout is {study}/{series_number}/, so
both resolved to the same folder and the second download silently OVERWROTE the
first — a real data-completeness loss; the viewer showed only one ("not connected").

Fix: `resolve_series_folder_name` makes the folder name collision-aware while keeping
the common (unique-number) case BYTE-IDENTICAL. On a collision the largest series
keeps the bare folder (so the viewer display is unchanged) and the other(s) are
preserved in a stable suffixed folder. `series_downloader` uses it and logs
`[SERIES_NUMBER_COLLISION]`. Flag: AIPACS_SERIES_NUMBER_DEDUP (default on).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import modules.download_manager.core.series_folder as sf  # noqa: E402

# (number, uid, image_count) for the live 86503 case
_S203_SMALL = (203, "1.2.840.010.202606180753363530000", 24)
_S203_BIG = (203, "1.2.840.1.99.1.47.2.1781767938298", 156)
_STUDY = [_S203_SMALL, _S203_BIG, (201, "uidX", 52), (202, "uidY", 156)]


# ---- common (no-collision) case is byte-identical -------------------------

def test_no_collision_returns_bare_number():
    assert sf.resolve_series_folder_name(201, "uidX", _STUDY) == "201"
    assert sf.resolve_series_folder_name(202, "uidY", _STUDY) == "202"


def test_single_series_study_unchanged():
    one = [(5, "only", 100)]
    assert sf.resolve_series_folder_name(5, "only", one) == "5"


# ---- collision: largest keeps bare, loser gets a stable suffix ------------

def test_collision_largest_keeps_bare_folder():
    # 156-image series 203 keeps "203" so the viewer display is unchanged
    assert sf.resolve_series_folder_name(203, _S203_BIG[1], _STUDY) == "203"


def test_collision_loser_gets_stable_suffix():
    name = sf.resolve_series_folder_name(203, _S203_SMALL[1], _STUDY)
    assert name != "203"
    assert name.startswith("203__")
    # stable / deterministic across calls
    assert name == sf.resolve_series_folder_name(203, _S203_SMALL[1], _STUDY)


def test_collision_two_folders_are_distinct():
    big = sf.resolve_series_folder_name(203, _S203_BIG[1], _STUDY)
    small = sf.resolve_series_folder_name(203, _S203_SMALL[1], _STUDY)
    assert big != small  # both series now live in distinct folders → no overwrite


def test_tie_on_image_count_breaks_by_lowest_uid():
    study = [(7, "bbb", 50), (7, "aaa", 50)]
    # equal counts → lowest uid ("aaa") keeps the bare folder
    assert sf.resolve_series_folder_name(7, "aaa", study) == "7"
    assert sf.resolve_series_folder_name(7, "bbb", study).startswith("7__")


def test_collisions_detector():
    cols = sf.series_number_collisions(_STUDY)
    assert cols == {"203"}


def test_missing_uid_returns_bare():
    assert sf.resolve_series_folder_name(203, "", _STUDY) == "203"


# ---- kill switch ----------------------------------------------------------

def test_flag_off_always_bare(monkeypatch):
    monkeypatch.setattr(sf, "_DEDUP_ENABLED", False)
    # even with a real collision, disabled → legacy bare number (both collide)
    assert sf.resolve_series_folder_name(203, _S203_SMALL[1], _STUDY) == "203"
    assert sf.resolve_series_folder_name(203, _S203_BIG[1], _STUDY) == "203"


def test_flag_default_on():
    assert 'AIPACS_SERIES_NUMBER_DEDUP", "1"' in (
        _REPO_ROOT / "modules/download_manager/core/series_folder.py"
    ).read_text(encoding="utf-8")


# ---- wiring into the downloader + mirror parity ---------------------------

def test_series_downloader_uses_helper_and_logs():
    src = (_REPO_ROOT / "modules/download_manager/download/series_downloader.py").read_text(encoding="utf-8")
    assert "resolve_series_folder_name(" in src
    assert "[SERIES_NUMBER_COLLISION]" in src
    assert "study_output_dir / _folder_name" in src


def test_plugin_mirror_carries_helper_and_wiring():
    base = _REPO_ROOT / "builder/plugin package/packages/download_manager/payload/python/modules/download_manager"
    helper = base / "core/series_folder.py"
    dl = base / "download/series_downloader.py"
    if not helper.exists() or not dl.exists():
        pytest.skip("download_manager plugin mirror not present")
    assert "resolve_series_folder_name" in helper.read_text(encoding="utf-8")
    assert "[SERIES_NUMBER_COLLISION]" in dl.read_text(encoding="utf-8")
