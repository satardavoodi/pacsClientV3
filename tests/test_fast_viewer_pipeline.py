from types import SimpleNamespace
import threading

from PacsClient.pacs.patient_tab.ui.patient_ui import patient_widget_viewer_controller as controller_mod


class _DummyVtkImage:
    def __init__(self, dims=(160, 160, 128)):
        self._dims = dims

    def GetDimensions(self):
        return self._dims


def _build_controller():
    controller = controller_mod.ViewerController.__new__(controller_mod.ViewerController)
    controller.logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )
    controller.lst_nodes_viewer = []
    controller._is_request_current = lambda *args, **kwargs: True
    controller._perform_series_switch_optimized = lambda *args, **kwargs: None
    return controller


def test_apply_loaded_series_data_rehydrates_parent_cache_without_refresh(tmp_path):
    controller = _build_controller()
    captured = {}
    series_dir = tmp_path / "study" / "5"
    series_dir.mkdir(parents=True)

    def _replace_series_data(**kwargs):
        captured.update(kwargs)
        return 3

    controller.parent_widget = SimpleNamespace(
        metadata_fixed={"patient_pk": 10, "study_pk": 20},
        replace_series_data=_replace_series_data,
        import_folder_path="",
    )

    controller._apply_loaded_series_data(
        series_number="5",
        vtk_image_data=_DummyVtkImage(),
        metadata={
            "series": {
                "thumbnail_path": "thumb.png",
                "series_path": str(series_dir),
            },
            "instances": [],
        },
        patient_pk=10,
        study_pk=20,
        refresh_viewer=False,
    )

    assert captured["allow_append_if_missing"] is True
    assert captured["series_number"] == "5"
    assert controller.parent_widget.import_folder_path == str(series_dir.parent)


def test_get_series_by_number_fast_rehydrates_from_full_cache(monkeypatch):
    controller = _build_controller()
    captured = {}
    vtk_data = _DummyVtkImage()
    metadata = {"series": {"series_number": "5", "thumbnail_path": "thumb.png"}}

    def _replace_series_data(series_number, vtk_image_data, metadata, file_path, allow_append_if_missing):
        captured["series_number"] = series_number
        captured["vtk_image_data"] = vtk_image_data
        captured["metadata"] = metadata
        captured["file_path"] = file_path
        captured["allow_append_if_missing"] = allow_append_if_missing
        return 0

    controller.parent_widget = SimpleNamespace(
        lst_thumbnails_data=[],
        replace_series_data=_replace_series_data,
    )
    controller._hot_series_cache = {}
    controller._series_cache = {}
    controller._series_number_to_index = {}
    controller._full_cache_get = lambda series_number: (vtk_data, metadata)
    controller._is_on_ui_thread = lambda: True
    controller._queue_on_ui_thread = lambda func: func()

    monkeypatch.setattr(controller_mod, "log_stage_timing", lambda *args, **kwargs: None)

    result = controller._get_series_by_number_fast("5")

    assert captured["allow_append_if_missing"] is True
    assert result == (vtk_data, metadata, 0)


def test_load_single_series_on_demand_uses_requested_fast_backend_when_backend_is_none(tmp_path, monkeypatch):
    controller = _build_controller()
    captured = {}
    study_root = tmp_path / "study"
    (study_root / "1").mkdir(parents=True)

    def _load_single_series_by_number(**kwargs):
        captured.update(kwargs)
        return None

    controller.parent_widget = SimpleNamespace(
        import_folder_path=str(study_root),
        metadata_fixed={"patient_pk": None, "study_pk": None},
        ordering_by_instances_number=None,
    )
    controller._get_requested_viewer_backend = lambda: controller_mod.BACKEND_PYDICOM
    controller._tab_active = True
    controller._interactive_load_in_progress = False
    controller.zeta_boost = SimpleNamespace(invalidate_series=lambda *args, **kwargs: None)
    controller._full_cache_get = lambda *args, **kwargs: None
    controller._get_series_by_number_fast = lambda *args, **kwargs: (None, None, -1)
    controller._series_load_lock = threading.Lock()
    controller._loading_series_numbers = set()
    controller._series_load_events = {}
    controller._interactive_full_load_semaphore = threading.BoundedSemaphore(1)
    controller._apply_loaded_series_data_threadsafe = lambda *args, **kwargs: None
    controller._prefetch_loaded = set()

    monkeypatch.setattr(controller_mod, "load_single_series_by_number", _load_single_series_by_number)
    monkeypatch.setattr(controller_mod, "log_stage_timing", lambda *args, **kwargs: None)

    result = controller._load_single_series_on_demand(series_number=1, viewer_backend=None)

    assert result is False
    assert captured["viewer_backend"] == controller_mod.BACKEND_PYDICOM
    assert captured["allow_lazy_backend"] is True
