"""Windows-on-ARM (emulated x64) runtime profile (ARM64 emulation strategy, 2026-07-07).

WHY THIS EXISTS
---------------
Decision: ARM64 machines run the proven x64 build under Prism emulation for
now (native VTK/MPR is a later phase). This module makes that path as smooth
and DIAGNOSABLE as possible: one `[WOA-PROFILE]` log block states the detected
architecture, the installed package type, whether VTK/MPR will run emulated,
and which optimizations were applied.

WHAT IT APPLIES (only when the process runs emulated on an ARM64 host, and
only for settings the USER has not already overridden via env):
- ``AIPACS_BROWSER_PREWARM=0`` — warming a Chromium engine under emulation is
  a large JIT cost for a rarely-used feature; the browser still works, it just
  warms on first real use (the OPT-22 idle-gate remains for x64 machines).

Deliberately NOT touched: decode workers, caches, render clocks, VTK/MPR
behavior — those are arch-neutral, and MPR stability on WoA is governed by the
GPU driver + Microsoft compatibility pack (see the Hardware Requirements
Check), not by app settings.

INVARIANTS
----------
- Native x64 machines: complete no-op (beyond one skipped-probe log line).
- Never raises; runs early in main.py right after the [RUNTIME_ARCH] banner.
- User env always wins: a pre-set variable is never overwritten.
- Kill switch ``AIPACS_WOA_PROFILE=0`` disables all tuning (logging remains).

Guard test: tests/code/system/test_woa_profile.py
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: (env var, value applied under emulation, why)
WOA_ENV_DEFAULTS: Tuple[Tuple[str, str, str], ...] = (
    (
        "AIPACS_BROWSER_PREWARM",
        "0",
        "Chromium prewarm is expensive under x64 emulation; warm on first use",
    ),
)


def _flag_enabled() -> bool:
    raw = os.getenv("AIPACS_WOA_PROFILE", "1").strip().lower()
    return raw not in ("0", "false", "off", "no")


def decide_woa_tuning(
    emulated: Optional[bool],
    environ: Dict[str, str],
    enabled: bool = True,
) -> List[Tuple[str, str, str]]:
    """PURE decision: which env defaults to apply. Empty unless emulated=True.

    Only variables ABSENT from ``environ`` are returned — an explicit user
    setting always wins.
    """
    if not enabled or emulated is not True:
        return []
    return [
        (name, value, why)
        for (name, value, why) in WOA_ENV_DEFAULTS
        if name not in environ
    ]


def installed_package_kind() -> str:
    """install_package stamped by the installer ("x64" / "x64_on_arm64" /
    "arm64"); "unknown" for pre-stamp installs and source runs."""
    try:
        from aipacs_runtime import load_installation_profile

        value = str(load_installation_profile().get("install_package") or "").strip()
        return value or "unknown"
    except Exception:
        return "unknown"


def apply_woa_runtime_profile() -> Dict[str, Any]:
    """Detect → log → tune. Called once from main.py; never raises."""
    result: Dict[str, Any] = {"emulated": None, "package": "unknown", "applied": []}
    try:
        from PacsClient.utils.runtime_arch_log import get_runtime_architecture

        arch = get_runtime_architecture()
        emulated = arch.get("emulated")
        package = installed_package_kind()
        result["emulated"] = emulated
        result["package"] = package

        if emulated is not True:
            return result  # native machine: no-op

        decisions = decide_woa_tuning(emulated, dict(os.environ), _flag_enabled())
        for name, value, why in decisions:
            os.environ[name] = value
            result["applied"].append(name)
            logger.warning("[WOA-PROFILE] set %s=%s (%s)", name, value, why)

        logger.warning(
            "[WOA-PROFILE] Windows-on-ARM emulated session: process=%s host=%s "
            "install_package=%s vtk_mpr=emulated-x64-via-OpenGLOn12 tuned=%s "
            "(profile flag AIPACS_WOA_PROFILE=%s). First launches are slower "
            "while Windows builds the x64 translation cache.",
            arch.get("process_arch"), arch.get("native_arch"), package,
            ",".join(result["applied"]) or "none", "on" if _flag_enabled() else "OFF",
        )
    except Exception as exc:
        try:
            logger.warning("[WOA-PROFILE] setup failed (ignored): %r", exc)
        except Exception:
            pass
    return result
