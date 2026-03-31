import modules.viewer.gpu_boost as gpu_boost


def test_load_gpu_boost_enabled_uses_runtime_profile(monkeypatch):
    monkeypatch.setattr(
        gpu_boost,
        "load_runtime_profile",
        lambda: {"graphics": {"user_declared_gpu": True}},
    )

    assert gpu_boost.load_gpu_boost_enabled(default=False) is True


def test_save_gpu_boost_enabled_updates_runtime_graphics(monkeypatch):
    captured = {}

    def _save_runtime_profile(patch):
        captured["patch"] = patch
        return patch

    monkeypatch.setattr(gpu_boost, "save_runtime_profile", _save_runtime_profile)

    result = gpu_boost.save_gpu_boost_enabled(True)

    assert result["graphics"]["user_declared_gpu"] is True
    assert result["graphics"]["preferred_mode"] == gpu_boost.GPU_BOOST_PREFERRED_MODE
    assert captured["patch"]["graphics"]["user_declared_gpu"] is True


def test_resolve_gpu_boost_plan_assigns_vtk_rendering_to_gpu(monkeypatch):
    monkeypatch.setattr(
        gpu_boost,
        "load_gpu_runtime_status",
        lambda: {
            "requested_gpu": True,
            "preferred_mode": gpu_boost.GPU_BOOST_PREFERRED_MODE,
            "last_detected_gpu": True,
            "last_probe_backend": "powershell_cim",
            "last_probe_device": "NVIDIA RTX 4060",
            "last_probe_utc": "2026-03-12T10:00:00Z",
        },
    )

    plan = gpu_boost.resolve_gpu_boost_plan(
        viewer_backend=gpu_boost.BACKEND_VTK,
        graphics_profile={
            "requested_gpu": True,
            "detected_gpu": True,
            "use_gpu": True,
            "device_name": "NVIDIA RTX 4060",
        },
    )

    assert plan["gpu_active"] is True
    assert plan["mode"] == "gpu"
    assert plan["fallback_reason"] == ""
    assert all(task["assigned_to"] == "gpu" for task in plan["gpu_tasks"])
    assert all(task["assigned_to"] == "cpu" for task in plan["cpu_tasks"])


def test_resolve_gpu_boost_plan_falls_back_for_cpu_only_backend(monkeypatch):
    monkeypatch.setattr(
        gpu_boost,
        "load_gpu_runtime_status",
        lambda: {
            "requested_gpu": True,
            "preferred_mode": gpu_boost.GPU_BOOST_PREFERRED_MODE,
            "last_detected_gpu": True,
            "last_probe_backend": "powershell_cim",
            "last_probe_device": "Intel Arc",
            "last_probe_utc": "2026-03-12T10:00:00Z",
        },
    )

    plan = gpu_boost.resolve_gpu_boost_plan(
        viewer_backend=gpu_boost.BACKEND_PYDICOM,
        graphics_profile={
            "requested_gpu": True,
            "detected_gpu": True,
            "use_gpu": True,
            "device_name": "Intel Arc",
        },
    )

    assert plan["gpu_active"] is False
    assert plan["mode"] == "cpu_fallback"
    assert "CPU-oriented" in plan["fallback_reason"]
    assert all(task["assigned_to"] == "cpu" for task in plan["cpu_tasks"])


def test_resolve_gpu_boost_plan_explains_software_opengl_fallback(monkeypatch):
    monkeypatch.setattr(
        gpu_boost,
        "load_gpu_runtime_status",
        lambda: {
            "requested_gpu": False,
            "preferred_mode": gpu_boost.GPU_BOOST_CPU_MODE,
            "last_detected_gpu": True,
            "last_probe_backend": "powershell_cim",
            "last_probe_device": "Intel Arc",
            "last_probe_utc": "2026-03-12T10:00:00Z",
            "last_execution_mode": "cpu_software_opengl",
            "last_software_rendering_status": "ready",
            "last_software_rendering_warning": "",
        },
    )

    plan = gpu_boost.resolve_gpu_boost_plan(
        viewer_backend=gpu_boost.BACKEND_VTK,
        graphics_profile={
            "requested_gpu": False,
            "detected_gpu": True,
            "use_gpu": False,
            "device_name": "Intel Arc",
        },
    )

    assert plan["gpu_active"] is False
    assert "Software OpenGL" in plan["fallback_reason"]


def test_resolve_gpu_boost_plan_mentions_safe_cpu_backend_when_software_runtime_is_incomplete(monkeypatch):
    monkeypatch.setattr(
        gpu_boost,
        "load_gpu_runtime_status",
        lambda: {
            "requested_gpu": False,
            "preferred_mode": gpu_boost.GPU_BOOST_CPU_MODE,
            "last_detected_gpu": False,
            "last_probe_backend": "",
            "last_probe_device": "",
            "last_probe_utc": "2026-03-13T08:00:00Z",
            "last_execution_mode": "cpu_software_opengl",
            "last_software_rendering_status": "partial",
            "last_software_rendering_warning": "Software OpenGL is only partially available. Missing runtime component(s): osmesa.dll.",
        },
    )

    plan = gpu_boost.resolve_gpu_boost_plan(
        viewer_backend=gpu_boost.BACKEND_VTK,
        graphics_profile={
            "requested_gpu": False,
            "detected_gpu": False,
            "use_gpu": False,
            "device_name": "",
        },
    )

    assert plan["gpu_active"] is False
    assert "PyDicom" in plan["fallback_reason"]
