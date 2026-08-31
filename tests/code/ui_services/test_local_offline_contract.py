"""Regression guards for a network-independent Local workflow.

Local search, single/multi-study preview, and an already-downloaded viewer must
never require the live PACS socket. Server mode keeps its refresh behavior.
"""

import ast
import asyncio
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
HP_SERIES = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py"
HP_SEARCH = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_search.py"
HP_MODULES = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_modules.py"
HP_OPEN = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py"
HP_IMPORT = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_import.py"
PW_THUMBS = REPO / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py"
PATIENT_UTILS = REPO / "PacsClient/pacs/patient_tab/utils/utils.py"
DB_MANAGER = REPO / "database/manager.py"
THUMBNAIL_MANAGER = REPO / "PacsClient/pacs/patient_tab/utils/thumbnail_manager.py"


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    node = next(
        item for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    return ast.get_source_segment(source, node)


def test_local_database_auto_sync_is_opt_in(monkeypatch):
    monkeypatch.delenv("AIPACS_LOCALDB_AUTO_SERVER_SYNC", raising=False)
    from modules.storage import sync_mode_policy as policy

    assert policy.requires_remote_resync("db") is False
    assert policy.requires_live_server_sync("db") is False
    assert policy.missing_files_trigger_server_download("db") is False

    monkeypatch.setenv("AIPACS_LOCALDB_AUTO_SERVER_SYNC", "1")
    assert policy.requires_remote_resync("db") is True


def test_single_click_reconcile_returns_local_rows_before_socket_access():
    body = _function_source(HP_SERIES, "_reconcile_patient_studies_on_click")
    gate = body.index("requires_remote_resync")
    socket = body.index("get_socket_patient_service")
    assert gate < socket
    assert "return local_uids" in body[gate:socket]


def test_local_cache_miss_returns_before_home_thumbnail_socket():
    body = _function_source(HP_SEARCH, "show_patient_studies")
    local_branch = body.index("right_panel_cache_miss_local_mode")
    socket = body.index("PatientListSocketClient")
    assert local_branch < socket
    assert "return" in body[local_branch:socket]
    assert "_build_local_series_thumbnail_payload" in body[local_branch:socket]


def test_grouped_local_preview_does_not_require_selected_server():
    body = _function_source(HP_MODULES, "_show_grouped_patient_studies")
    local_gate = body.index("local_is_source_of_truth")
    server_lookup = body.index("get_server_selected")
    assert local_gate < server_lookup
    assert "_build_local_series_thumbnail_payload" in body


def test_local_viewer_thumbnail_cache_miss_returns_before_socket_import():
    body = _function_source(PW_THUMBS, "_load_server_thumbnails_async")
    local_branch = body.index("patient_tab_thumb_cache_miss_local_mode")
    socket = body.index("PatientListSocketClient")
    assert local_branch < socket
    assert "return" in body[local_branch:socket]


def test_local_viewer_reconciles_db_series_before_accepting_a_partial_cache_hit():
    body = _function_source(PW_THUMBS, "_load_server_thumbnails_async")
    cache_accept = body.index("if thumbnails:")
    local_reconcile = body.index("series_entries = await asyncio.to_thread")

    assert local_reconcile < cache_accept


def test_local_pipeline_never_renders_storage_thumbnail_stems_as_drag_handles(monkeypatch):
    """Local cards must wait for DB identity projection, not use ``1_2.png``.

    Python accepts underscores in integer strings (``int("1_2") == 12``), so
    rendering the persisted collision filename as an early UI key silently
    redirects a drag to a non-existent Series 12 and leaves the later Series 1
    card unable to repair its 25-image count.
    """
    from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core import _pw_pipeline
    from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_pipeline import _PWPipelineMixin
    from PacsClient.utils import CallerTypes

    class _LocalPipeline(_PWPipelineMixin):
        study_uid = "synthetic-study"
        import_folder_path = "synthetic-local-root"
        _progressive_display_enabled = True

        def __init__(self):
            self.legacy_thumbnail_renders = 0

        def _get_default_layout_from_config(self):
            return (1, 1)

        def _local_thumbnail_workflow(self):
            return True

        def show_exist_thumbnails(self):
            self.legacy_thumbnail_renders += 1
            return 2

        def apply_multi_viewer(self, *_args, **_kwargs):
            return None

        def _show_viewer_loading_all(self):
            return None

    pipeline = _LocalPipeline()
    monkeypatch.setattr(_pw_pipeline, "check_and_get_thumbnails", lambda *_args: ["1.png", "1_2.png"])

    async def _run():
        pipeline.pipeline_manager(CallerTypes.SERVER)

    asyncio.run(_run())

    assert pipeline.legacy_thumbnail_renders == 0


def test_fast_drop_parser_rejects_collision_storage_keys_instead_of_coercing_them():
    """``1_2`` is storage identity, never numeric UI identity.

    Python's integer parser accepts digit separators, so validation must happen
    before conversion or ``1_2`` is silently routed as Series 12.
    """
    from PySide6.QtCore import QMimeData

    from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.qt_fast_container import (
        QtFastContainer,
        _SERIES_DROP_MIME,
    )

    mime_data = QMimeData()
    mime_data.setData(_SERIES_DROP_MIME, b"1_2")

    assert QtFastContainer._extract_series_number(object(), mime_data) is None


def test_local_open_does_not_refresh_existing_tab_or_previous_exams_from_server():
    body = _function_source(HP_OPEN, "_on_patient_double_clicked_async")
    assert "local_is_source_of_truth" in body
    refresh = body.index("_OPEN_REFRESH_ALREADY_OPEN")
    resync = body.index("_resync_patient_studies_from_server", refresh)
    assert "local_is_source_of_truth" in body[refresh:resync]
    previous = body.index("init_previous_exams")
    assert "if not is_local" in body[max(0, previous - 400):previous]


def test_local_multistudy_open_pushes_disk_series_metadata_to_viewer():
    body = _function_source(HP_OPEN, "_on_patient_double_clicked_async")
    background = body.index("def _background_setup_thread")
    aggregate = body.index("aggregated_series = []", background)
    push = body.index("widget.set_server_series_info(series_list)", aggregate)
    local_branch = body.index("if is_local:", aggregate, push)

    assert "_build_local_series_thumbnail_payload" in body[local_branch:push]
    assert "for current_study_uid in all_study_uids" in body[local_branch:push]


def test_persisted_series_path_is_the_local_collision_storage_key():
    from PacsClient.utils.patient_study_set import persisted_series_folder_key

    assert persisted_series_folder_key("5", r"D:\dicom\study\5__deadbeef") == "5__deadbeef"
    assert persisted_series_folder_key("5", "/dicom/study/5__deadbeef/") == "5__deadbeef"
    assert persisted_series_folder_key("5", "") == "5"


def test_local_thumbnail_projection_carries_exact_series_path_and_folder_key():
    db_body = _function_source(DB_MANAGER, "get_study_info_with_series")
    home_body = _function_source(HP_SEARCH, "_build_local_series_thumbnail_payload")
    viewer_body = _function_source(PW_THUMBS, "_build_local_thumbnail_entries")

    assert "series_path" in db_body
    for body in (home_body, viewer_body):
        assert "persisted_series_folder_key" in body
        assert "'folder_key': folder_key" in body
        assert "'series_path': series_path" in body


def test_local_thumbnail_projection_excludes_non_pixel_dicom_objects():
    for body in (
        _function_source(HP_SEARCH, "_build_local_series_thumbnail_payload"),
        _function_source(PW_THUMBS, "_build_local_thumbnail_entries"),
    ):
        assert "inspect_series_pixel_inventory" in body
        assert "if not pixel_inventory.has_pixel_data" in body
        assert "pixel_inventory.pixel_instance_count" in body


def test_local_pixel_inventory_counts_cine_frames_not_only_dicom_objects(tmp_path):
    import numpy as np
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

    from PacsClient.utils.dicom_displayability import inspect_series_pixel_inventory

    for index, frames in enumerate((2, 3), start=1):
        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        path = tmp_path / f"cine-{index}.dcm"
        ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
        ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID = generate_uid()
        ds.SeriesInstanceUID = generate_uid()
        ds.PatientID = "TEST"
        ds.Modality = "US"
        ds.Rows = 1
        ds.Columns = 1
        ds.NumberOfFrames = frames
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = 8
        ds.BitsStored = 8
        ds.HighBit = 7
        ds.PixelRepresentation = 0
        ds.PixelData = np.arange(frames, dtype=np.uint8).tobytes()
        ds.save_as(path, write_like_original=False)

    inventory = inspect_series_pixel_inventory(tmp_path)
    assert inventory.instance_count == 2
    assert inventory.pixel_instance_count == 2
    assert inventory.frame_count == 5
    assert inventory.display_image_count == 5


def test_cine_card_uses_frame_count_without_changing_file_completeness_count():
    home_body = _function_source(HP_SEARCH, "_build_local_series_thumbnail_payload")
    viewer_body = _function_source(PW_THUMBS, "_build_local_thumbnail_entries")
    card_body = _function_source(THUMBNAIL_MANAGER, "create_thumbnail_widget")

    for body in (home_body, viewer_body):
        assert "'image_count': pixel_inventory.pixel_instance_count" in body
        assert "'display_image_count': pixel_inventory.display_image_count" in body
    assert "'display_image_count', series_info.get('image_count', 0)" in card_body


def test_local_count_persistence_targets_duplicate_series_by_series_uid():
    render_body = _function_source(PW_THUMBS, "_render_thumbnails_from_entries")
    update_body = _function_source(DB_MANAGER, "update_series_image_count_by_uid")

    assert "series.get('series_uid')" in render_body
    assert "series_uid=series_uid" in render_body
    assert "AND series_uid = ?" in update_body


def test_image_count_update_changes_only_the_requested_series_uid(monkeypatch):
    import database.manager as manager

    executed = []

    class _Cursor:
        rowcount = 1

        def execute(self, sql, params):
            executed.append((" ".join(sql.split()), params))

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return _Cursor()

        def commit(self):
            return None

    monkeypatch.setattr(manager, "find_study_pk_with_study_uid", lambda _uid: 17)
    monkeypatch.setattr(manager.database, "get_db_connection", lambda: _Connection())

    assert manager.update_series_image_count_by_uid(
        "study-uid",
        "1",
        25,
        series_uid="image-series-uid",
    ) is True
    assert executed == [
        (
            "UPDATE series SET image_count = ? WHERE study_fk = ? AND series_uid = ?",
            (25, 17, "image-series-uid"),
        )
    ]


def test_missing_local_thumbnail_is_rebuilt_from_the_exact_disk_folder_offline():
    build_body = _function_source(PW_THUMBS, "_build_local_thumbnail_entries")
    repair_body = _function_source(PATIENT_UTILS, "repair_local_series_thumbnail")

    assert "repair_local_series_thumbnail" in build_body
    assert "load_series_preview" in repair_body
    assert "series_number=folder_key" in repair_body
    assert "save_image_as_png" in repair_body


def test_import_fast_prepare_uses_collision_aware_storage_key_for_load_and_thumbnail():
    body = _function_source(HP_IMPORT, "_prepare_imported_study_for_fast_open")

    assert 'series.get("folder_key")' in body
    assert 'series.get("series_path_name")' in body
    assert 'thumbnail_root / f"{storage_key}.png"' in body
    assert "series_number=storage_key" in body


def test_patient_tab_separates_digit_only_ui_handle_from_collision_storage_key():
    sink_body = _function_source(PW_THUMBS, "set_server_series_info")
    render_body = _function_source(PW_THUMBS, "_render_thumbnails_from_entries")

    assert "allocate_series_display_keys" in sink_body
    assert "series['folder_key'] = folder_key" in sink_body
    assert "entry_key = str(series.get('display_key') or series_number)" in sink_body
    assert "entry_key = str(series.get('display_key') or series_number)" in render_body
    assert "key_thumbnail=entry_key" in render_body
