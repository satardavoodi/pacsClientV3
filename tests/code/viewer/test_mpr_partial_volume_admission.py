"""MPR must not accept a partial Advanced payload as the completed series."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import vtkmodules.all as vtk

from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.toolbar_manager import ToolbarManager


@pytest.mark.parametrize("path", ["orthogonal", "curved", "projection", "dental"])
@pytest.mark.parametrize("preview", [True, False])
def test_partial_advanced_payload_is_blocked_without_decoding(path, preview):
    image = vtk.vtkImageData()
    image.SetDimensions(4, 4, 8)
    image.AllocateScalars(vtk.VTK_SHORT, 1)
    metadata = {"series": {"viewer_backend": "vtk_simpleitk"},
                "preview_only": preview, "instances": [{} for _ in range(8 if preview else 104)]}
    state = SimpleNamespace(_emit_mpr_launch_route=Mock())
    before = image.GetMTime()
    result, route = ToolbarManager._resolve_mpr_volume_for_route(
        state, series_data={"vtk_image_data": image, "metadata": metadata},
        series_number="1", mpr_path=path)
    assert result is None
    assert route["reason"] == ("incomplete_source_volume" if preview else "inconsistent_source_volume")
    assert image.GetMTime() == before
    assert len(metadata["instances"]) == (8 if preview else 104)
    assert state._emit_mpr_launch_route.call_args.kwargs["status"] == "blocked"


def test_completed_advanced_volume_still_uses_existing_pixels():
    image = vtk.vtkImageData()
    image.SetDimensions(4, 4, 104)
    image.AllocateScalars(vtk.VTK_SHORT, 1)
    metadata = {"series": {"viewer_backend": "vtk_simpleitk"},
                "preview_only": False, "instances": [{} for _ in range(104)]}
    state = SimpleNamespace(_emit_mpr_launch_route=Mock())
    result, route = ToolbarManager._resolve_mpr_volume_for_route(
        state, series_data={"vtk_image_data": image, "metadata": metadata},
        series_number="1", mpr_path="orthogonal")
    assert result is image
    assert route["reason"] == "using_existing_volume"


def test_partial_admission_messages_explain_recovery():
    assert "loading" in ToolbarManager._mpr_route_block_message("incomplete_source_volume").lower()
    assert "reload" in ToolbarManager._mpr_route_block_message("inconsistent_source_volume").lower()
