"""Process / OS architecture + Windows-on-ARM emulation detection (OPT-21).

WHY THIS EXISTS
---------------
PC2 ("baba") turned out to be a Snapdragon X Elite laptop running Windows 11
ARM64. Our frozen build is x64, so on that machine the whole app (Python, Qt,
VTK, numpy) runs under Windows' Prism x64 emulator, and OpenGL is served by
the Microsoft "OpenGL on D3D12" compatibility layer (Mesa GLon12 →
OpenGLOn12.dll → D3D12 → Adreno). None of this was visible in our logs — the
startup slowness and the MPR native crash could not be attributed. This module
makes the architecture situation explicit in the FIRST lines of app.log.

DETECTION
---------
``platform.machine()`` inside an x64-emulated process reports ``AMD64`` (the
emulated view). The reliable host signal is ``IsWow64Process2``'s
*nativeMachine* output (0xAA64 = ARM64). We therefore report:
process_arch (what the process believes), native_arch (what the machine is),
and emulated = native ARM64 while the process is AMD64/x86.

INVARIANTS
----------
- stdlib + ctypes only; must NEVER raise (startup path).
- Call ``log_runtime_architecture()`` AFTER logging is configured.

Guard test: tests/code/system/test_runtime_arch_log.py
"""

from __future__ import annotations

import logging
import os
import platform
import sys
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_MACHINE_NAMES = {
    0x0000: None,        # IMAGE_FILE_MACHINE_UNKNOWN (not WOW64 / not reported)
    0x014C: "x86",
    0x01C4: "ARMNT",
    0x8664: "AMD64",
    0xAA64: "ARM64",
}


def _native_machine_via_iswow64process2() -> Optional[str]:
    """Host machine per IsWow64Process2 (Windows 10 1709+); None off-Windows/unknown."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        if not hasattr(kernel32, "IsWow64Process2"):
            return None
        process_machine = ctypes.c_ushort(0)
        native_machine = ctypes.c_ushort(0)
        ok = kernel32.IsWow64Process2(
            kernel32.GetCurrentProcess(),
            ctypes.byref(process_machine),
            ctypes.byref(native_machine),
        )
        if not ok:
            return None
        return _MACHINE_NAMES.get(native_machine.value, hex(native_machine.value))
    except Exception:
        return None


def get_runtime_architecture() -> Dict[str, Any]:
    """Gather process/OS architecture facts. Never raises."""
    info: Dict[str, Any] = {
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": os.path.basename(sys.executable or "?"),
        "process_arch": (platform.machine() or "?").upper(),
        "env_processor_architecture": os.environ.get("PROCESSOR_ARCHITECTURE"),
        "env_processor_identifier": os.environ.get("PROCESSOR_IDENTIFIER"),
        "native_arch": None,
        "emulated": None,
    }
    try:
        native = _native_machine_via_iswow64process2()
        info["native_arch"] = native
        if native:
            proc = info["process_arch"]
            if native == "ARM64" and proc in ("AMD64", "X86", "I386", "I686"):
                info["emulated"] = True   # x64/x86 build under Windows-on-ARM (Prism)
            elif native == proc:
                info["emulated"] = False
            elif native in ("AMD64",) and proc in ("X86",):
                info["emulated"] = True   # classic WOW64
            else:
                info["emulated"] = False
    except Exception:
        pass
    return info


def log_runtime_architecture() -> Dict[str, Any]:
    """Log one structured [RUNTIME_ARCH] line (call after logging is configured)."""
    info = get_runtime_architecture()
    try:
        logger.warning(
            "[RUNTIME_ARCH] process_arch=%s native_arch=%s emulated=%s frozen=%s "
            "python=%s exe=%s env_arch=%s cpu_id=%r",
            info.get("process_arch"), info.get("native_arch"), info.get("emulated"),
            info.get("frozen"), info.get("python"), info.get("executable"),
            info.get("env_processor_architecture"), info.get("env_processor_identifier"),
        )
        if info.get("emulated"):
            logger.warning(
                "[RUNTIME_ARCH] x64 build running under Windows-on-ARM emulation (Prism): "
                "expect slower startup (JIT translation) and OpenGL served via the "
                "Microsoft D3D12 mapping layer (OpenGLOn12/Mesa GLon12)."
            )
    except Exception:
        pass
    return info
