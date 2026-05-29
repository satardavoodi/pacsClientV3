from PacsClient.pacs.patient_tab.utils import image_io


def test_load_vtk_from_dicom_paths_emits_with_safe_series_number(monkeypatch):
    dummy_vtk = object()
    calls = []

    monkeypatch.setattr(image_io, "get_itk_image", lambda paths: object())
    monkeypatch.setattr(image_io.utils, "convert_itk2vtk", lambda itk_image: dummy_vtk)

    def _capture_emit(series_number, **_kwargs):
        calls.append(series_number)

    monkeypatch.setattr(image_io, "_emit_advanced_vtk_orientation_audit_stage", _capture_emit)

    result = image_io.load_vtk_from_dicom_paths(["C:/fake/series/001.dcm"])

    assert result is dummy_vtk
    assert calls == ["unknown", "unknown"]


def test_load_vtk_from_dicom_paths_ignores_audit_emit_failures(monkeypatch):
    dummy_vtk = object()

    monkeypatch.setattr(image_io, "get_itk_image", lambda paths: object())
    monkeypatch.setattr(image_io.utils, "convert_itk2vtk", lambda itk_image: dummy_vtk)
    monkeypatch.setattr(
        image_io,
        "_emit_advanced_vtk_orientation_audit_stage",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("audit emit failed")),
    )

    result = image_io.load_vtk_from_dicom_paths(["C:/fake/series/001.dcm"])

    assert result is dummy_vtk
