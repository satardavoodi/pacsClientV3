"""Per-series selection for the CD burn workflow (2026-07-30).

When a selection is active, ``CDBurnWorker._collect_study_folders`` must feed the
DICOMDIR builder / preparer ONLY the chosen series subfolders — no selection must
stay byte-identical (the whole study folder).
"""

from __future__ import annotations

from pathlib import Path

from modules.cd_burner.cd_burn_manager import CDBurnWorker, _normalize_series_number


def _make_study(tmp_path: Path):
    study_uid = "1.2.3.4.5"
    root = tmp_path / study_uid
    for series in ("2", "3", "4"):
        (root / series).mkdir(parents=True)
        # extension-less file with no suffix — _has_dicom_files reads tags, so
        # write a byte file the has-check will accept via its rglob('*.dcm') path
        (root / series / f"IM_{series}.dcm").write_bytes(b"x" * 200)
    return study_uid, str(root)


def test_no_selection_returns_whole_study_folder(tmp_path):
    study_uid, path = _make_study(tmp_path)
    w = CDBurnWorker(studies=[{"study_uid": study_uid, "study_path": path}])
    folders = w._series_folders_for_study(path, study_uid)
    assert folders == [path]


def test_selection_returns_only_chosen_series_subfolders(tmp_path):
    study_uid, path = _make_study(tmp_path)
    w = CDBurnWorker(
        studies=[{"study_uid": study_uid, "study_path": path}],
        series_selection={study_uid: {"2", "4"}},
    )
    folders = w._series_folders_for_study(path, study_uid)
    names = sorted(Path(f).name for f in folders)
    assert names == ["2", "4"]  # series 3 excluded


def test_collect_study_folders_applies_selection(tmp_path):
    study_uid, path = _make_study(tmp_path)
    w = CDBurnWorker(
        studies=[{"study_uid": study_uid, "study_path": path}],
        series_selection={study_uid: {"3"}},
    )
    folders = w._collect_study_folders()
    assert sorted(Path(f).name for f in folders) == ["3"]


def test_study_absent_from_selection_map_keeps_whole_study(tmp_path):
    study_uid, path = _make_study(tmp_path)
    w = CDBurnWorker(
        studies=[{"study_uid": study_uid, "study_path": path}],
        series_selection={"different-study": {"2"}},
    )
    assert w._series_folders_for_study(path, study_uid) == [path]


def test_empty_selection_fails_safe_to_whole_study(tmp_path):
    study_uid, path = _make_study(tmp_path)
    w = CDBurnWorker(
        studies=[{"study_uid": study_uid, "study_path": path}],
        series_selection={study_uid: set()},
    )
    assert w._series_folders_for_study(path, study_uid) == [path]


def test_selection_that_matches_nothing_falls_back_to_whole_study(tmp_path):
    study_uid, path = _make_study(tmp_path)
    w = CDBurnWorker(
        studies=[{"study_uid": study_uid, "study_path": path}],
        series_selection={study_uid: {"99"}},  # no such series folder
    )
    # never produce an empty disc — burn the whole study instead
    assert w._series_folders_for_study(path, study_uid) == [path]


def test_kill_switch_disables_the_filter(tmp_path, monkeypatch):
    monkeypatch.setenv("AIPACS_EXPORT_SERIES_SELECTION", "0")
    study_uid, path = _make_study(tmp_path)
    w = CDBurnWorker(
        studies=[{"study_uid": study_uid, "study_path": path}],
        series_selection={study_uid: {"2"}},
    )
    assert w._series_folders_for_study(path, study_uid) == [path]


def test_normalize_series_number():
    assert _normalize_series_number("02") == "2"
    assert _normalize_series_number(3) == "3"
    assert _normalize_series_number("2.0") == "2"
    assert _normalize_series_number("SCOUT") == "SCOUT"
    assert _normalize_series_number("") == ""
