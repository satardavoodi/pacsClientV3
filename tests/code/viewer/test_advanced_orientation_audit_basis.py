"""Diagnostic handedness checks; never alter patient/display geometry to fit a log."""
import logging
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import vtkmodules.all as vtk

from modules.viewer.advanced.viewer_2d import ImageViewer2D


@pytest.mark.parametrize("row,col", [
    ([1, 0, 0], [0, 1, 0]),
    ([0, 1, 0], [0, 0, 1]),
    ([1, 0, 0], [0, 0, 1]),
    ([2**-0.5, 2**-0.5, 0], [0, 0, 1]),
])
@pytest.mark.parametrize("flipped", [False, True])
def test_camera_basis_audit_is_consistent_and_observational(row, col, flipped, caplog):
    row, col = np.array(row, dtype=float), np.array(col, dtype=float)
    normal = np.cross(row, col)
    camera = vtk.vtkCamera()
    camera.SetPosition(*(-normal))
    camera.SetFocalPoint(0, 0, 0)
    camera.SetViewUp(*(col if flipped else -col))
    image = vtk.vtkImageData()
    image.SetDimensions(2, 2, 1)
    state = SimpleNamespace(
        metadata={"series": {}, "instances": [{"ImageOrientationPatient": [*row, *col]}]},
        renderer=SimpleNamespace(GetActiveCamera=lambda: camera),
        vtk_image_data=image, GetImageActor=lambda: vtk.vtkImageActor(),
        _classify_orientation_failure=Mock(return_value="F"),
    )
    for name in ("_safe_unit", "_vec_angle_deg", "_matrix_to_tuple3"):
        setattr(state, name, MethodType(getattr(ImageViewer2D, name), state))
    before = (camera.GetMTime(), image.GetMTime(), camera.GetPosition(), camera.GetViewUp())
    with caplog.at_level(logging.WARNING):
        ImageViewer2D._emit_advanced_vtk_orientation_audit(state, 0)
    assert before == (camera.GetMTime(), image.GetMTime(), camera.GetPosition(), camera.GetViewUp())
    message = next(r.getMessage() for r in caplog.records if "[ADVANCED_VTK_ORIENTATION_AUDIT]" in r.getMessage())
    assert "normal_mismatch_deg=0.0" in message
    assert f"camera_iop_basis_match={not flipped}" in message
    assert "orientation_valid=not_evaluated" in message
    assert "comparison_scope=unregistered_camera_vs_dicom" in message


def test_audit_report_does_not_promote_camera_diagnostic_to_geometry_proof(tmp_path, capsys):
    from tools.diagnostics._advanced_vtk_orientation_audit_report import build_report
    log = tmp_path / "synthetic.log"
    log.write_text(
        "[ADVANCED_VTK_ORIENTATION_AUDIT] viewport_id=synthetic plane=AXIAL "
        "camera_iop_basis_match=True orientation_valid=not_evaluated "
        "comparison_scope=unregistered_camera_vs_dicom legacy_failure_hint=F\n",
        encoding="utf-8",
    )
    build_report(log)
    output = capsys.readouterr().out
    assert "PROOF TABLE" not in output
    assert "not_evaluated" in output
    assert "unregistered_camera_vs_dicom" in output
    assert "diagnostic" in output.lower()
