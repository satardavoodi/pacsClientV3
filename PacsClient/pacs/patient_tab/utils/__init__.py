from __future__ import annotations

from .thumbnail_manager import ThumbnailManager
from .utils import (
    BoxManager,
    DicomTagsActors,
    TYPES_VIEWER,
    VerticalButton,
    check_and_get_thumbnails,
    check_folder_has_dicom,
    check_series_study_exist,
    check_study_complete,
    check_study_exists,
    clear_study_cache,
    count_study_series_instances,
    count_subfolders_with_dicom,
    create_attachment_folder,
    create_random_string,
    delete_widgets_in_layout,
    get_all_series_thumbnail_from_study_folder,
    get_count_dicom_files_exist,
    get_name_file_from_path,
    get_quickly_series_info,
    get_study_download_status,
    get_study_source_path,
    has_subfolders,
    last_added_file,
    list_subfolders_with_dicom,
    load_json_as_dict,
    open_folder,
    save_image_as_png,
    save_series_json,
    save_thumbnail_with_bytes,
    show_message,
    validate_thumbnail_files,
)
from .patient_sync_service import PatientSyncService, get_patient_sync_service
from .node_viewer import NodeViewer
from .series_layout_matrix import MatrixSelector
from .corner_labels import make_corner_actor

__all__ = [
    "ThumbnailManager",
    "load_images",
    "read_segment_nifti",
    "load_images_from_server",
    "save_image_as_png",
    "delete_widgets_in_layout",
    "DicomTagsActors",
    "create_attachment_folder",
    "open_folder",
    "create_random_string",
    "save_thumbnail_with_bytes",
    "check_study_exists",
    "check_study_complete",
    "get_study_download_status",
    "validate_thumbnail_files",
    "save_series_json",
    "get_all_series_thumbnail_from_study_folder",
    "load_json_as_dict",
    "get_study_source_path",
    "check_series_study_exist",
    "check_and_get_thumbnails",
    "get_name_file_from_path",
    "clear_study_cache",
    "get_quickly_series_info",
    "get_count_dicom_files_exist",
    "count_subfolders_with_dicom",
    "list_subfolders_with_dicom",
    "last_added_file",
    "BoxManager",
    "TYPES_VIEWER",
    "show_message",
    "VerticalButton",
    "check_folder_has_dicom",
    "count_study_series_instances",
    "has_subfolders",
    "PatientSyncService",
    "get_patient_sync_service",
    "NodeViewer",
    "MatrixSelector",
    "make_corner_actor",
]


def load_images(*args, **kwargs):
    from .image_io import load_images as _load_images

    return _load_images(*args, **kwargs)


def read_segment_nifti(*args, **kwargs):
    from .image_io import read_segment_nifti as _read_segment_nifti

    return _read_segment_nifti(*args, **kwargs)


def load_images_from_server(*args, **kwargs):
    from .image_io import load_images_from_server as _load_images_from_server

    return _load_images_from_server(*args, **kwargs)
