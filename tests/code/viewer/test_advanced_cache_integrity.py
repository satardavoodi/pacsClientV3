"""Decoded Advanced pixels and per-frame metadata remain a single payload."""
import copy
import logging
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
import vtkmodules.all as vtk

from PacsClient.pacs.patient_tab.ui.patient_ui._vc_cache import _VCCacheMixin
from PacsClient.pacs.patient_tab.ui.patient_ui._vc_backend import _VCBackendMixin


def payload(count=8, depth=8, backend="vtk_simpleitk", preview=False):
    image = vtk.vtkImageData()
    image.SetDimensions(4, 4, depth)
    metadata = {"series": {"series_number": "1", "viewer_backend": backend},
                "instances": [{"instance_number": i, "instance_path": f"synthetic/{i}.dcm"} for i in range(count)],
                "preview_only": preview}
    return image, metadata


@pytest.mark.parametrize("count,depth,frames,valid", [(104,8,1,False),(8,104,1,False),(8,8,1,True),(1,8,8,True)])
def test_full_cache_requires_matching_decoded_frames(count, depth, frames, valid):
    image, metadata = payload(count, depth)
    for item in metadata["instances"]:
        item["number_of_frames"] = frames
    state = NS(_get_series_expected_slices=lambda _: 104)
    assert _VCCacheMixin._is_full_volume_cache_candidate(state, "1", image, metadata) is valid


def test_refresh_cannot_extend_advanced_preview_or_scan_disk(tmp_path):
    image, metadata = payload(preview=True)
    metadata["series"]["series_path"] = str(tmp_path)
    (tmp_path / "new.dcm").write_bytes(b"synthetic")
    before = copy.deepcopy(metadata)
    state = NS(_series_number_to_index={"1":0}, parent_widget=NS(lst_thumbnails_data=[{"metadata":metadata,"vtk_image_data":image}]),
               _series_cache={}, _hot_series_cache={}, _count_series_files_on_disk=Mock(return_value=104),
               _schedule_background_header_fill=Mock(), logger=logging.getLogger(__name__))
    _VCCacheMixin._refresh_stored_metadata_instances(state,"1",104)
    assert metadata == before
    state._count_series_files_on_disk.assert_not_called()
    assert not state._hot_series_cache


@pytest.mark.parametrize("backend,expected", [("vtk_simpleitk",8),("pydicom_qt",104)])
def test_live_metadata_growth_is_fast_only(backend,expected):
    _, source = payload(104,104,backend)
    _, target = payload(8,8,backend,True)
    state = NS(_series_number_to_index={"1":0}, parent_widget=NS(lst_thumbnails_data=[{"metadata":source}]),
               lst_nodes_viewer=[NS(vtk_widget=NS(image_viewer=NS(metadata=target)))],logger=logging.getLogger(__name__))
    _VCCacheMixin._sync_viewer_metadata_instances(state,"1")
    assert len(target["instances"]) == expected


def test_hot_main_and_index_cannot_reseed_inconsistent_volume():
    image, metadata = payload(104,8)
    item={"metadata":metadata,"vtk_image_data":image}
    state=NS(parent_widget=NS(lst_thumbnails_data=[item]),_hot_series_cache={"1":(image,metadata,0)},
             _series_cache={"1":(image,metadata,0)},_series_number_to_index={"1":0},
             _full_cache_get=Mock(return_value=None),logger=logging.getLogger(__name__))
    assert _VCBackendMixin._get_series_by_number_fast(state,"1") == (None,None,-1)
    assert not state._hot_series_cache and not state._series_cache


def test_matching_preview_is_readable_but_not_a_full_cache_candidate():
    image, metadata = payload(preview=True)
    state=NS(parent_widget=NS(lst_thumbnails_data=[{"metadata":metadata,"vtk_image_data":image}]),
             _hot_series_cache={"1":(image,metadata,0)}, _series_cache={}, _series_number_to_index={"1":0},
             logger=logging.getLogger(__name__))
    assert _VCBackendMixin._get_series_by_number_fast(state,"1")[0] is image
    assert not _VCCacheMixin._is_full_volume_cache_candidate(state,"1",image,metadata)


def test_invalid_tiers_fall_through_to_completed_volume():
    old, old_meta = payload(104,8)
    full, full_meta = payload(104,104)
    state=NS(parent_widget=NS(lst_thumbnails_data=[{"metadata":old_meta,"vtk_image_data":old}]),
             _hot_series_cache={"1":(old,old_meta,0)},_series_cache={"1":(old,old_meta,0)},
             _series_number_to_index={"1":0},_full_cache_get=lambda _: (full,full_meta),
             logger=logging.getLogger(__name__), _is_on_ui_thread=lambda: False, _queue_on_ui_thread=Mock())
    result = _VCBackendMixin._get_series_by_number_fast(state,"1")
    assert result[0] is full and result[1] is full_meta


def test_frame_expanded_multiframe_metadata_is_accepted():
    image, metadata = payload(8,8)
    for item in metadata["instances"]:
        item["number_of_frames"] = 8
    state = NS(_get_series_expected_slices=lambda _: 8)
    assert _VCCacheMixin._is_full_volume_cache_candidate(state,"1",image,metadata)
