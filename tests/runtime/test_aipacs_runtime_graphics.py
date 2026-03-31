from datetime import datetime, timezone

import aipacs_runtime as runtime


def test_build_graphics_runtime_patch_records_probe_metadata():
    patch = runtime.build_graphics_runtime_patch(
        {
            "detected_gpu": True,
            "detector": "powershell_cim",
            "device_name": "Intel Arc",
        },
        probed_at=datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )

    assert patch == {
        "graphics": {
            "last_detected_gpu": True,
            "last_probe_backend": "powershell_cim",
            "last_probe_device": "Intel Arc",
            "last_probe_utc": "2026-03-12T12:00:00Z",
            "last_execution_mode": "",
            "last_software_rendering_status": "",
            "last_software_rendering_warning": "",
        }
    }


def test_detect_software_graphics_support_uses_env_overrides(monkeypatch, tmp_path):
    qt_dll = tmp_path / "opengl32sw.dll"
    osmesa_dll = tmp_path / "osmesa.dll"
    pipe_dll = tmp_path / "pipe_swrast.dll"
    qt_dll.write_text("", encoding="utf-8")
    osmesa_dll.write_text("", encoding="utf-8")
    pipe_dll.write_text("", encoding="utf-8")
    monkeypatch.setenv(runtime.QT_SOFTWARE_OPENGL_DLL_ENV, str(qt_dll))
    monkeypatch.setenv(runtime.VTK_OSMESA_DLL_ENV, str(osmesa_dll))
    monkeypatch.chdir(tmp_path)

    support = runtime.detect_software_graphics_support()

    assert support["ready"] is True
    assert support["status"] == "ready"
    assert support["qt_opengl_dll"] == str(qt_dll)
    assert support["vtk_osmesa_dll"] == str(osmesa_dll)
    assert support["vtk_pipe_swrast_dll"] == str(pipe_dll)


def test_resolve_graphics_profile_skips_probe_when_gpu_not_requested(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "load_runtime_profile",
        lambda: {"graphics": {"user_declared_gpu": False, "preferred_mode": "cpu_safe"}},
    )
    monkeypatch.setattr(
        runtime,
        "detect_software_graphics_support",
        lambda: {
            "qt_opengl_dll": "C:/runtime/opengl32sw.dll",
            "vtk_osmesa_dll": "C:/runtime/osmesa.dll",
            "vtk_pipe_swrast_dll": "C:/runtime/pipe_swrast.dll",
            "qt_ready": True,
            "vtk_ready": True,
            "vtk_pipe_ready": True,
            "ready": True,
            "status": "ready",
            "missing": [],
            "warning": "",
        },
    )

    def _unexpected_probe():
        raise AssertionError("probe_gpu_support should not be called")

    monkeypatch.setattr(runtime, "probe_gpu_support", _unexpected_probe)

    profile = runtime.resolve_graphics_profile()

    assert profile["requested_gpu"] is False
    assert profile["use_gpu"] is False
    assert profile["detected_gpu"] is False
    assert profile["execution_mode"] == runtime.GRAPHICS_EXECUTION_SOFTWARE
    assert profile["software_rendering_ready"] is True


def test_resolve_graphics_profile_uses_probe_when_gpu_requested(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "load_runtime_profile",
        lambda: {"graphics": {"user_declared_gpu": True, "preferred_mode": "prefer_gpu"}},
    )
    monkeypatch.setattr(
        runtime,
        "detect_software_graphics_support",
        lambda: {
            "qt_opengl_dll": "C:/runtime/opengl32sw.dll",
            "vtk_osmesa_dll": "C:/runtime/osmesa.dll",
            "vtk_pipe_swrast_dll": "C:/runtime/pipe_swrast.dll",
            "qt_ready": True,
            "vtk_ready": True,
            "vtk_pipe_ready": True,
            "ready": True,
            "status": "ready",
            "missing": [],
            "warning": "",
        },
    )
    monkeypatch.setattr(
        runtime,
        "probe_gpu_support",
        lambda: {
            "has_gpu": True,
            "devices": [{"name": "Intel Iris"}],
            "detector": "powershell_cim",
            "error": "",
        },
    )

    profile = runtime.resolve_graphics_profile()

    assert profile["requested_gpu"] is True
    assert profile["detected_gpu"] is True
    assert profile["use_gpu"] is True
    assert profile["device_name"] == "Intel Iris"
    assert profile["execution_mode"] == runtime.GRAPHICS_EXECUTION_GPU


def test_build_windows_graphics_environment_targets_software_opengl(monkeypatch):
    monkeypatch.setattr(runtime, "install_root", lambda: runtime.Path("C:/AIPacs"))

    plan = runtime.build_windows_graphics_environment(
        {
            "use_gpu": False,
            "software_rendering": {
                "qt_opengl_dll": "C:/runtime/opengl32sw.dll",
                "vtk_osmesa_dll": "C:/runtime/osmesa.dll",
                "vtk_pipe_swrast_dll": "C:/runtime/pipe_swrast.dll",
                "qt_ready": True,
                "vtk_ready": True,
                "vtk_pipe_ready": True,
                "ready": True,
                "status": "ready",
                "missing": [],
                "warning": "",
            },
        },
        frozen=False,
    )

    assert plan["execution_mode"] == runtime.GRAPHICS_EXECUTION_SOFTWARE
    assert plan["env"]["QT_OPENGL"] == "software"
    assert plan["env"]["QT_OPENGL_DLL"] == "opengl32sw"
    assert plan["env"]["VTK_DEFAULT_OPENGL_WINDOW"] == "vtkOSOpenGLRenderWindow"
    assert runtime.SAFE_VIEWER_BACKEND_ENV not in plan["env"]
    assert "--disable-software-rasterizer" not in plan["env"]["QTWEBENGINE_CHROMIUM_FLAGS"]


def test_build_windows_graphics_environment_reports_missing_osmesa(monkeypatch):
    monkeypatch.setattr(runtime, "install_root", lambda: runtime.Path("C:/AIPacs"))

    plan = runtime.build_windows_graphics_environment(
        {
            "use_gpu": False,
            "software_rendering": {
                "qt_opengl_dll": "C:/runtime/opengl32sw.dll",
                "vtk_osmesa_dll": "",
                "vtk_pipe_swrast_dll": "C:/runtime/pipe_swrast.dll",
                "qt_ready": True,
                "vtk_ready": False,
                "vtk_pipe_ready": True,
                "ready": False,
                "status": "partial",
                "missing": ["osmesa.dll"],
                "warning": "Software OpenGL is only partially available. Missing runtime component(s): osmesa.dll.",
            },
        },
        frozen=False,
    )

    assert "VTK_DEFAULT_OPENGL_WINDOW" not in plan["env"]
    assert "osmesa.dll" in plan["warning"]
    assert plan["env"][runtime.SAFE_VIEWER_BACKEND_ENV] == runtime.SAFE_VIEWER_BACKEND_DEFAULT
    assert plan["viewer_backend_override"] == runtime.SAFE_VIEWER_BACKEND_DEFAULT
