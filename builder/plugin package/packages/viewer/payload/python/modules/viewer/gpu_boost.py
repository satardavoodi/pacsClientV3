"""GPU Boost preference and task routing for viewer workloads.

This module keeps GPU preference persistence lightweight and centralizes the
viewer-side decision about which workloads are GPU-eligible versus CPU-bound.
The actual graphics bootstrap still happens in ``main.py`` before Qt/VTK
initialization; changing the preference therefore applies on next launch.
"""

from __future__ import annotations

from typing import Any

from aipacs_runtime import load_runtime_profile, resolve_graphics_profile, save_runtime_profile


BACKEND_VTK = "vtk_simpleitk"
BACKEND_PYDICOM = "pydicom_2d"
BACKEND_PYDICOM_QT = "pydicom_qt"

GPU_BOOST_PREFERRED_MODE = "prefer_gpu"
GPU_BOOST_CPU_MODE = "cpu_safe"

_GPU_CAPABLE_VIEWER_BACKENDS = {BACKEND_VTK}


def load_gpu_boost_enabled(default: bool = False) -> bool:
    """Return the persisted viewer GPU preference."""
    try:
        profile = load_runtime_profile()
        graphics = profile.get("graphics") or {}
        return bool(graphics.get("user_declared_gpu", default))
    except Exception:
        return bool(default)


def save_gpu_boost_enabled(enabled: bool) -> dict[str, Any]:
    """Persist the viewer GPU preference into the runtime graphics profile."""
    requested = bool(enabled)
    return save_runtime_profile(
        {
            "graphics": {
                "user_declared_gpu": requested,
                "preferred_mode": GPU_BOOST_PREFERRED_MODE if requested else GPU_BOOST_CPU_MODE,
            }
        }
    )


def load_gpu_runtime_status() -> dict[str, Any]:
    """Return the cached runtime graphics status saved by the bootstrap path."""
    try:
        profile = load_runtime_profile()
    except Exception:
        profile = {}
    graphics = profile.get("graphics") or {}
    return {
        "requested_gpu": bool(graphics.get("user_declared_gpu", False)),
        "preferred_mode": str(graphics.get("preferred_mode") or GPU_BOOST_CPU_MODE),
        "last_detected_gpu": bool(graphics.get("last_detected_gpu", False)),
        "last_probe_backend": str(graphics.get("last_probe_backend") or ""),
        "last_probe_device": str(graphics.get("last_probe_device") or ""),
        "last_probe_utc": str(graphics.get("last_probe_utc") or ""),
        "last_execution_mode": str(graphics.get("last_execution_mode") or ""),
        "last_software_rendering_status": str(graphics.get("last_software_rendering_status") or ""),
        "last_software_rendering_warning": str(graphics.get("last_software_rendering_warning") or ""),
    }


def _task(
    task_id: str,
    label: str,
    current_engine: str,
    assigned_to: str,
    gpu_eligible: bool,
    notes: str,
) -> dict[str, Any]:
    return {
        "task": task_id,
        "label": label,
        "current_engine": current_engine,
        "assigned_to": assigned_to,
        "gpu_eligible": bool(gpu_eligible),
        "notes": notes,
    }


def resolve_gpu_boost_plan(
    viewer_backend: str | None = None,
    graphics_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve viewer GPU usage and stable CPU fallback behavior.

    The returned plan is intentionally declarative so the UI and backend can
    both inspect the same policy:
    - ``gpu_active`` identifies whether viewer rendering should use GPU.
    - ``gpu_tasks`` enumerates tasks that can benefit from GPU.
    - ``cpu_tasks`` enumerates tasks that remain CPU-owned.
    - ``fallback_reason`` explains why CPU fallback is active when relevant.
    """
    runtime_status = load_gpu_runtime_status()
    profile = dict(graphics_profile or resolve_graphics_profile() or {})

    requested_gpu = bool(profile.get("requested_gpu", runtime_status["requested_gpu"]))
    detected_gpu = bool(profile.get("detected_gpu", runtime_status["last_detected_gpu"]))
    device_name = str(
        profile.get("device_name")
        or runtime_status.get("last_probe_device")
        or ""
    ).strip()

    backend = str(viewer_backend or BACKEND_VTK).strip().lower() or BACKEND_VTK
    backend_gpu_capable = backend in _GPU_CAPABLE_VIEWER_BACKENDS
    gpu_active = bool(profile.get("use_gpu", requested_gpu and detected_gpu and backend_gpu_capable))
    gpu_active = bool(gpu_active and backend_gpu_capable)

    fallback_reason = ""
    if not requested_gpu:
        if backend_gpu_capable:
            software_status = str(runtime_status.get("last_software_rendering_status") or "").strip()
            software_warning = str(runtime_status.get("last_software_rendering_warning") or "").strip()
            if software_status == "ready":
                fallback_reason = (
                    "GPU Boost is disabled in Viewer Configuration. On next launch, "
                    "the workstation targets CPU + Software OpenGL for the VTK/SimpleITK path."
                )
            elif software_warning:
                fallback_reason = (
                    "GPU Boost is disabled in Viewer Configuration. The workstation "
                    "targets CPU + Software OpenGL on next launch, but the software "
                    f"graphics runtime is incomplete: {software_warning} "
                    "Until it is available, the workstation will force the safe PyDicom CPU backend."
                )
            else:
                fallback_reason = (
                    "GPU Boost is disabled in Viewer Configuration. The workstation "
                    "targets CPU + Software OpenGL on next launch."
                )
        else:
            fallback_reason = "GPU Boost is disabled in Viewer Configuration."
    elif not backend_gpu_capable:
        fallback_reason = (
            "The selected viewer backend is CPU-oriented; VTK/SimpleITK is the "
            "only GPU-capable viewer render path in the current architecture."
        )
    elif not detected_gpu:
        fallback_reason = "No compatible GPU was detected, so the viewer stays on the CPU path."

    gpu_tasks = [
        _task(
            "image_rendering",
            "Image rendering",
            "VTK render window / OpenGL",
            "gpu" if gpu_active else "cpu",
            True,
            "2D viewer frame composition can use GPU only on the VTK/SimpleITK backend.",
        ),
        _task(
            "display_reslice",
            "Display reslice and viewport updates",
            "VTK image reslice / mapper",
            "gpu" if gpu_active else "cpu",
            True,
            "Interactive display updates are GPU-eligible when hardware rendering is active.",
        ),
        _task(
            "volume_ray_cast",
            "3D volume ray casting",
            "vtkGPUVolumeRayCastMapper",
            "gpu" if gpu_active else "cpu",
            True,
            "Used by 3D/MPR paths that already rely on VTK GPU mappers.",
        ),
    ]
    cpu_tasks = [
        _task(
            "dicom_io",
            "DICOM file I/O",
            "pydicom / SimpleITK reader",
            "cpu",
            False,
            "Series discovery and disk reads remain CPU-bound.",
        ),
        _task(
            "metadata_and_geometry",
            "Metadata parsing and geometry validation",
            "database / pydicom / numpy",
            "cpu",
            False,
            "Series metadata and coordinate bookkeeping stay on CPU for determinism.",
        ),
        _task(
            "image_preprocessing",
            "Filter preprocessing",
            "SimpleITK / OpenCV / numpy",
            "cpu",
            False,
            "Filter chains are still CPU-based in the current backend implementation.",
        ),
        _task(
            "lazy_decode_and_prefetch",
            "Lazy decode, warmup, and cache management",
            "PyDicom / ZetaBoost workers",
            "cpu",
            False,
            "Slice decode and warmup orchestration remain CPU tasks even when rendering uses GPU.",
        ),
    ]

    return {
        "viewer_backend": backend,
        "backend_gpu_capable": backend_gpu_capable,
        "requested_gpu": requested_gpu,
        "detected_gpu": detected_gpu,
        "gpu_active": gpu_active,
        "device_name": device_name,
        "mode": "gpu" if gpu_active else "cpu_fallback",
        "fallback_reason": fallback_reason,
        "restart_required": True,
        "gpu_tasks": gpu_tasks,
        "cpu_tasks": cpu_tasks,
        "engine_paths": [
            {
                "engine": "VTK/OpenGL viewer render path",
                "gpu_capable": True,
                "active": backend == BACKEND_VTK,
            },
            {
                "engine": "PyDicom lazy 2D path",
                "gpu_capable": False,
                "active": backend == BACKEND_PYDICOM,
            },
            {
                "engine": "PyDicom Qt bridge path",
                "gpu_capable": False,
                "active": backend == BACKEND_PYDICOM_QT,
            },
            {
                "engine": "SimpleITK/OpenCV preprocessing path",
                "gpu_capable": False,
                "active": True,
            },
        ],
    }
