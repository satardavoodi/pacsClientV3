from pathlib import Path
from types import SimpleNamespace

from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_thumbnails import _PWThumbnailsMixin
from PacsClient.utils.series_completeness import build_series_completeness_snapshot


def test_completeness_snapshot_detects_incomplete_and_disk_growth():
    snapshot = build_series_completeness_snapshot(
        "201",
        expected_count=10,
        metadata_count=4,
        disk_count=6,
    )

    assert snapshot.metadata_behind_disk is True
    assert snapshot.is_incomplete is True
    assert snapshot.is_disk_complete is False


def test_completeness_snapshot_treats_unknown_expected_as_any_local_data():
    snapshot = build_series_completeness_snapshot(
        "202",
        expected_count=0,
        disk_count=1,
        viewer_visible_count=1,
    )

    assert snapshot.is_disk_complete is True
    assert snapshot.is_viewer_complete is True
    assert snapshot.is_incomplete is False


class _ThumbnailProbe(_PWThumbnailsMixin):
    def __init__(self, base_path: Path, expected_count: int):
        self.import_folder_path = str(base_path)
        self._server_series_info = {"201": {"image_count": expected_count}}
        self._series_uid_to_number = {}

    def _get_correct_study_path(self):
        return self.import_folder_path


def test_is_series_downloaded_requires_expected_count(tmp_path):
    study_path = tmp_path / "study"
    series_path = study_path / "201"
    series_path.mkdir(parents=True)
    for idx in range(3):
        (series_path / f"Instance_{idx:04d}.dcm").write_bytes(b"dcm")

    probe = _ThumbnailProbe(study_path, expected_count=4)

    assert probe._is_series_downloaded("201") is False

    (series_path / "Instance_0003.dcm").write_bytes(b"dcm")

    assert probe._is_series_downloaded("201") is True