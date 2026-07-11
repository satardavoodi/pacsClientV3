"""Guard tests — Windows-on-ARM graphics fix (live crash fix, 2026-07-08).

ROOT CAUSE proven by the production faulthandler on a Snapdragon X Elite:
the bundled software OpenGL (Mesa llvmpipe / opengl32sw.dll) executes a SIMD
instruction Prism's x64-on-ARM emulator cannot run → 0xc000001d ILLEGAL
INSTRUCTION at vtk_widget.Initialize(). The machine's hardware D3D12/Adreno
OpenGL works (GLview: GL 4.6). So on emulated WoA the software profile must
NOT force llvmpipe — it must use the system/desktop hardware GL.

Pins: robust emulation detection (IsWow64Process2 was unreliable on the live
box) + the inverted graphics branch, with the AIPACS_WOA_FORCE_SOFTWARE_GL
escape hatch. Pure/env-driven — no Qt/VTK needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import aipacs_runtime as runtime  # noqa: E402


# ---------------------------------------------------------------------------
# Robust emulation detection
# ---------------------------------------------------------------------------

def _force_win32(monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "win32")


def test_emulated_via_iswow64(monkeypatch):
    _force_win32(monkeypatch)
    monkeypatch.setattr(runtime, "_native_machine_name", lambda: "ARM64")
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    assert runtime.native_host_arch() == "ARM64"
    assert runtime.is_windows_on_arm_emulated() is True


def test_emulated_via_fallback_when_iswow64_blank(monkeypatch):
    # The live Snapdragon case: IsWow64Process2 returned nothing, but the CPU
    # identifier + PROCESSOR_ARCHITECTURE mismatch reveal emulation.
    _force_win32(monkeypatch)
    monkeypatch.setattr(runtime, "_native_machine_name", lambda: "")
    monkeypatch.delenv("PROCESSOR_ARCHITEW6432", raising=False)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    monkeypatch.setenv(
        "PROCESSOR_IDENTIFIER", "ARMv8 (64-bit) Family 8 Model 1 Revision 201, Qualcomm Technologies Inc"
    )
    assert runtime.native_host_arch() == "ARM64"
    assert runtime.is_windows_on_arm_emulated() is True


def test_native_x64_not_emulated(monkeypatch):
    _force_win32(monkeypatch)
    monkeypatch.setattr(runtime, "_native_machine_name", lambda: "AMD64")
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    monkeypatch.setenv("PROCESSOR_IDENTIFIER", "Intel64 Family 6")
    monkeypatch.delenv("PROCESSOR_ARCHITEW6432", raising=False)
    assert runtime.is_windows_on_arm_emulated() is False


def test_non_windows_never_emulated(monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    assert runtime.is_windows_on_arm_emulated() is False


# ---------------------------------------------------------------------------
# Graphics environment branch
# ---------------------------------------------------------------------------

def _software_profile():
    return {
        "use_gpu": False,
        "software_rendering": {
            "ready": True,
            "qt_opengl_dll": r"C:\eng\opengl32sw.dll",
            "vtk_osmesa_dll": r"C:\eng\osmesa.dll",
            "vtk_pipe_swrast_dll": r"C:\eng\pipe_swrast.dll",
            "warning": "",
        },
    }


def test_woa_emulated_uses_hardware_gl_not_llvmpipe(monkeypatch):
    monkeypatch.setattr(runtime, "is_windows_on_arm_emulated", lambda: True)
    monkeypatch.delenv("AIPACS_WOA_FORCE_SOFTWARE_GL", raising=False)
    out = runtime.build_windows_graphics_environment(_software_profile(), frozen=True)
    env = out["env"]
    # hardware/desktop GL, NOT the crashing software path
    assert env.get("QT_OPENGL") == "desktop"
    assert env.get("VTK_USE_HARDWARE") == "1"
    assert env.get("AIPACS_WOA_GRAPHICS") == "hardware_desktop_gl"
    assert "GALLIUM_DRIVER" not in env
    assert "LIBGL_ALWAYS_SOFTWARE" not in env
    assert "VTK_OPENGL_FORCE_SOFTPIPE" not in env
    assert "QT_OPENGL_DLL" not in env
    # the software Mesa DLLs must NOT be forced onto PATH
    joined = " ".join(out["path_prefixes"]).lower()
    assert "opengl32sw" not in joined and "osmesa" not in joined and "pipe_swrast" not in joined
    # the legacy software vars are still CLEARED so nothing leaks from a prior run
    assert "GALLIUM_DRIVER" in out["clear_env"]
    assert "VTK_OPENGL_FORCE_SOFTPIPE" in out["clear_env"]


def test_woa_escape_hatch_restores_software(monkeypatch):
    monkeypatch.setattr(runtime, "is_windows_on_arm_emulated", lambda: True)
    monkeypatch.setenv("AIPACS_WOA_FORCE_SOFTWARE_GL", "1")
    env = runtime.build_windows_graphics_environment(_software_profile(), frozen=True)["env"]
    assert env.get("QT_OPENGL") == "software"
    assert env.get("GALLIUM_DRIVER") == "llvmpipe"
    assert env.get("VTK_OPENGL_FORCE_SOFTPIPE") == "1"


def test_non_woa_software_path_unchanged(monkeypatch):
    monkeypatch.setattr(runtime, "is_windows_on_arm_emulated", lambda: False)
    env = runtime.build_windows_graphics_environment(_software_profile(), frozen=True)["env"]
    # classic x64 software machine: byte-identical legacy behavior
    assert env.get("QT_OPENGL") == "software"
    assert env.get("GALLIUM_DRIVER") == "llvmpipe"
    assert env.get("VTK_USE_HARDWARE") == "0"
    assert "AIPACS_WOA_GRAPHICS" not in env


def test_explicit_gpu_profile_untouched_on_woa(monkeypatch):
    monkeypatch.setattr(runtime, "is_windows_on_arm_emulated", lambda: True)
    gpu_profile = {"use_gpu": True, "software_rendering": {}}
    env = runtime.build_windows_graphics_environment(gpu_profile, frozen=True)["env"]
    # already-hardware GPU profile is the normal GPU branch, not the WoA branch
    assert env.get("VTK_USE_HARDWARE") == "1"
    assert "AIPACS_WOA_GRAPHICS" not in env
