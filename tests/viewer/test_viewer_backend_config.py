import modules.viewer.viewer_backend_config as backend_config
from aipacs_runtime import SAFE_VIEWER_BACKEND_ENV


def test_resolve_viewer_backend_honors_safe_backend_override(monkeypatch):
    monkeypatch.setenv(SAFE_VIEWER_BACKEND_ENV, backend_config.BACKEND_PYDICOM)
    monkeypatch.setattr(
        backend_config,
        "load_viewer_backend",
        lambda default=backend_config.DEFAULT_BACKEND: backend_config.BACKEND_VTK,
    )

    resolution = backend_config.resolve_viewer_backend(metadata=None, settings=backend_config.BACKEND_VTK)

    assert resolution["configured_backend"] == backend_config.BACKEND_VTK
    assert resolution["requested_backend"] == backend_config.BACKEND_PYDICOM_QT
    assert resolution["backend"] == backend_config.BACKEND_VTK
    assert resolution["metadata_complete"] is False
    assert resolution["safe_backend_forced"] is True


def test_resolve_viewer_backend_keeps_configured_backend_without_override(monkeypatch):
    monkeypatch.delenv(SAFE_VIEWER_BACKEND_ENV, raising=False)
    monkeypatch.setattr(
        backend_config,
        "load_viewer_backend",
        lambda default=backend_config.DEFAULT_BACKEND: backend_config.BACKEND_VTK,
    )

    resolution = backend_config.resolve_viewer_backend(metadata=None, settings=backend_config.BACKEND_VTK)

    assert resolution["configured_backend"] == backend_config.BACKEND_VTK
    assert resolution["requested_backend"] == backend_config.BACKEND_VTK
    assert resolution["safe_backend_forced"] is False


def test_resolve_viewer_backend_avoids_vtk_fallback_when_safe_override_and_instances_exist(monkeypatch):
    monkeypatch.setenv(SAFE_VIEWER_BACKEND_ENV, backend_config.BACKEND_PYDICOM)

    resolution = backend_config.resolve_viewer_backend(
        metadata={
            "series": {
                "force_vtk_fallback": True,
            },
            "instances": [{"instance_path": "C:/study/1.dcm"}],
        },
        settings=backend_config.BACKEND_VTK,
    )

    assert resolution["safe_backend_forced"] is True
    assert resolution["backend"] == backend_config.BACKEND_PYDICOM_QT
