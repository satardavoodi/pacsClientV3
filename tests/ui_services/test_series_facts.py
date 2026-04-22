from types import SimpleNamespace

from PacsClient.pacs.patient_tab.ui.patient_ui import _vc_backend as _vc_backend_mod
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core import _pw_thumbnails as _pw_thumbnails_mod
from PacsClient.utils.series_facts import resolve_series_expected_count


def test_resolve_series_expected_count_prefers_server_info_over_partial_thumbnail_instances():
    resolution = resolve_series_expected_count(
        "uid-201",
        uid_to_number_map={"uid-201": "201"},
        series_info_map={"201": {"image_count": 12}},
        thumbnail_items=[
            {
                "metadata": {
                    "series": {"series_number": "201"},
                    "instances": [{"instance_number": i} for i in range(3)],
                }
            }
        ],
    )

    assert resolution.series_identifier == "201"
    assert resolution.expected_count == 12
    assert resolution.source == "series_info.image_count"


def test_resolve_series_expected_count_uses_preview_total_before_other_sources():
    resolution = resolve_series_expected_count(
        "201",
        metadata_flat_map={
            "201": {
                "preview_only": True,
                "preview_total_instances": 25,
                "instances": [{"instance_number": 0}],
            }
        },
        series_info_map={"201": {"image_count": 12}},
    )

    assert resolution.expected_count == 25
    assert resolution.source == "metadata_flat.preview_total_instances"


def test_series_expected_count_resolution_builds_completeness_snapshot():
    resolution = resolve_series_expected_count(
        "201",
        series_info_map={"201": {"image_count": 10}},
    )

    snapshot = resolution.to_completeness_snapshot(
        metadata_count=4,
        disk_count=6,
        viewer_visible_count=6,
    )

    assert snapshot.expected_count == 10
    assert snapshot.metadata_behind_disk is True
    assert snapshot.is_incomplete is True


def test_controller_expected_slice_helper_delegates_to_shared_series_facts(monkeypatch):
    class _Probe(_vc_backend_mod._VCBackendMixin):
        pass

    probe = _Probe()
    probe._warmup_max_slices = 32
    probe._prefetch_skip_slices_threshold = 16
    probe._metadata_flat_cache = {}
    probe._series_number_to_index = {}
    probe.parent_widget = SimpleNamespace(
        _series_uid_to_number={},
        _server_series_info={},
        lst_thumbnails_data=[],
    )
    probe._get_correct_study_path = lambda: None

    monkeypatch.setattr(
        _vc_backend_mod,
        "resolve_series_expected_count",
        lambda *args, **kwargs: SimpleNamespace(expected_count=27),
    )

    assert probe._get_series_expected_slices("201") == 27


def test_thumbnail_expected_count_helper_delegates_to_shared_series_facts(monkeypatch):
    class _Probe(_pw_thumbnails_mod._PWThumbnailsMixin):
        pass

    probe = _Probe()
    probe._series_uid_to_number = {}
    probe._server_series_info = {}
    probe.lst_thumbnails_data = []

    monkeypatch.setattr(
        _pw_thumbnails_mod,
        "resolve_series_expected_count",
        lambda *args, **kwargs: SimpleNamespace(expected_count=19),
    )

    assert probe._get_expected_series_image_count("uid-201") == 19