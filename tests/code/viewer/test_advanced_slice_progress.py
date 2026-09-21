"""Known series size is presentation information, never a larger navigable range."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from modules.viewer.advanced.viewer_2d import ImageViewer2D


def state_for(metadata, count=8):
    metadata.setdefault("series", {}).update(series_name="Synthetic", series_description="Synthetic")
    return SimpleNamespace(
        metadata=metadata, metadata_fixed={}, GetSlice=lambda: 0,
        get_display_slice=lambda: 0, skip_slices=0,
        get_count_of_slices=lambda: count, _overlay_identity=lambda: None,
        dicom_tags_actors=SimpleNamespace(), renderer=Mock(), Render=Mock(),
    )


def test_preview_corner_reports_total_and_ready_count():
    state = state_for({"preview_only": True, "preview_total_instances": 80})
    ImageViewer2D.load_top_right_actors(state, render=False)
    assert state.dicom_tags_actors.im_slice_actor.GetInput() == "1 / 80 (8 ready)"
    assert state.get_count_of_slices() == 8


@pytest.mark.parametrize("metadata,count,expected", [
    ({"preview_only": False, "preview_total_instances": 140}, 80, "1 / 80"),
    ({"preview_only": True}, 8, "1 / 8 (Loading)"),
    ({"preview_only": True, "preview_total_instances": "bad"}, 8, "1 / 8 (Loading)"),
    ({"preview_only": True, "preview_total_instances": 3}, 8, "1 / 8 (Loading)"),
    ({"preview_only": True, "preview_total_instances": 80}, 80, "1 / 80 (Loading)"),
])
def test_count_state_does_not_invent_or_retain_total(metadata, count, expected):
    state = state_for(metadata, count)
    ImageViewer2D.load_top_right_actors(state, render=False)
    assert state.dicom_tags_actors.im_slice_actor.GetInput() == expected


def test_scroll_and_complete_bind_update_same_counter_without_stale_preview():
    state = state_for({"preview_only": True, "preview_total_instances": 80})
    state.metadata["series"]["series_thk"] = "1"
    state.metadata["instances"] = [{"rows": 8, "columns": 10}] * 8
    state.get_window_level = lambda: (400, 40)
    ImageViewer2D.load_top_right_actors(state, render=False)
    state.dicom_tags_actors.change_actor_text = lambda actor, text: actor.SetInput(text)
    for name in ("im_series_thk_actor", "im_series_size_actor", "im_series_window_level"):
        setattr(state.dicom_tags_actors, name, Mock())
    state.GetSlice = lambda: 7
    state.get_display_slice = lambda: 7
    ImageViewer2D._update_corners_actors_impl(state)
    assert state.dicom_tags_actors.im_slice_actor.GetInput() == "8 / 80 (8 ready)"
    state.metadata["preview_only"] = False
    state.get_count_of_slices = lambda: 80
    ImageViewer2D._update_corners_actors_impl(state)
    assert state.dicom_tags_actors.im_slice_actor.GetInput() == "8 / 80"
