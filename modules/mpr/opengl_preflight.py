"""OpenGL pre-flight + persisted hardware check for VTK-based MPR/3D (OPT-21).

WHY THIS EXISTS
---------------
On an end-user PC whose display driver cannot provide a modern OpenGL context
(generic "Microsoft Basic Display Adapter", ancient GPU driver, some RDP
sessions), constructing the FIRST VTK OpenGL render window kills the whole
process with a NATIVE access violation — no Python traceback, all logs stop
mid-line (PC2 crash 2026-07-07 14:48: process death inside
``_mpr_views._create_axial_view``). VTK's OpenGL2 backend requires OpenGL >= 3.2.
The FAST 2D viewer is VTK-free by design, so such a machine works perfectly
until the user presses MPR — then the entire workstation dies.

WHAT THIS DOES
--------------
- ``opengl_preflight()`` — the MPR gate. Consults the PERSISTED hardware-check
  result first (``<config>/hardware_check.json``): a persisted PASS is trusted
  with **zero probing** (the check runs once per install, not per session/click
  — user directive 2026-07-07, "prevents MPR from being slow"). Only when the
  file is missing or recorded a FAILURE does it probe now (graceful Qt probe,
  a few ms) and persist — so a machine whose driver was UPGRADED self-heals on
  the next MPR attempt.
- ``run_hardware_check()`` — the full on-demand check behind the Settings →
  Viewer Configuration → "Hardware Requirements Check" panel
  (``settings_ui/hardware_check_panel.py``): OpenGL/GPU, CPU cores, RAM, free
  disk, each with ok/warning/fail status. Persists the result.

INVARIANTS
----------
- Import-light: Qt only inside the probe; psutil/data_paths lazily.
- The probe and every persistence helper must NEVER raise.
- ``evaluate_opengl_support`` / ``evaluate_hardware`` are PURE (unit-testable).
- Only the OpenGL item gates MPR; CPU/RAM/disk are informational.
- Flag ``AIPACS_MPR_OPENGL_PREFLIGHT`` (default ON). ``=0`` -> gate returns
  ``(True, "preflight disabled")`` = byte-identical legacy (no probe, no block).
- ``hardware_check.json`` is MACHINE-GENERATED STATE — never ship/seed it as a
  config template (seeding would copy the dev machine's results to end users).
- A passing probe is a pre-filter, not a guarantee; a failing probe reliably
  predicts a native VTK crash and must block.

Guard test: tests/code/viewer/test_mpr_opengl_preflight.py
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: Minimum OpenGL version required by VTK 9's OpenGL2 rendering backend.
MIN_GL_VERSION: Tuple[int, int] = (3, 2)

PERSIST_FILENAME = "hardware_check.json"
PERSIST_SCHEMA = 1

_cached_result: Optional[Tuple[bool, str]] = None
_persist_path_override: Optional[str] = None


# ---------------------------------------------------------------------------
# Flag / persistence plumbing (never raises)
# ---------------------------------------------------------------------------

def _flag_enabled() -> bool:
    """AIPACS_MPR_OPENGL_PREFLIGHT default ON; '0'/'false'/'off'/'no' disables."""
    raw = os.getenv("AIPACS_MPR_OPENGL_PREFLIGHT", "1").strip().lower()
    return raw not in ("0", "false", "off", "no")


def _persist_path() -> Optional[str]:
    """Resolve <config dir>/hardware_check.json (same dir the viewer settings use)."""
    if _persist_path_override is not None:
        return _persist_path_override
    try:
        from PacsClient.utils.config import SOCKET_CONFIG_PATH  # config DIR
        return os.path.join(str(SOCKET_CONFIG_PATH), PERSIST_FILENAME)
    except Exception:
        return None


def load_persisted_check() -> Optional[Dict[str, Any]]:
    """Read the persisted hardware-check result; None when absent/unreadable."""
    try:
        path = _persist_path()
        if not path or not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_persisted_check(result: Dict[str, Any]) -> bool:
    """Write the hardware-check result. Best-effort; returns success."""
    try:
        path = _persist_path()
        if not path:
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
        return True
    except Exception as exc:
        try:
            logger.warning("[HW_CHECK] persist failed: %r", exc)
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
# Pure decisions (no Qt — unit-testable)
# ---------------------------------------------------------------------------

def evaluate_opengl_support(
    created: bool,
    major: int,
    minor: int,
    min_version: Tuple[int, int] = MIN_GL_VERSION,
) -> Tuple[bool, str]:
    """PURE decision: is this (context-created, version) good enough for VTK?"""
    if not created:
        return False, "OpenGL context creation failed (no usable GPU driver)"
    try:
        version = (int(major), int(minor))
    except (TypeError, ValueError):
        return False, f"OpenGL version unreadable (major={major!r} minor={minor!r})"
    if version < tuple(min_version):
        return (
            False,
            f"OpenGL {version[0]}.{version[1]} is below the required "
            f"{min_version[0]}.{min_version[1]}",
        )
    return True, f"OpenGL {version[0]}.{version[1]}"


def evaluate_hardware(raw: Dict[str, Any]) -> Dict[str, Any]:
    """PURE evaluation of gathered hardware facts -> per-item statuses.

    ``raw`` keys: ``opengl`` (dict from the probe), ``cpu_cores``,
    ``ram_bytes``, ``disk_free_bytes`` (any may be None/missing).
    Statuses: ``ok`` / ``warning`` / ``fail``. Only ``opengl`` gates MPR.
    """
    items = []

    gl = raw.get("opengl") or {}
    gl_ok = bool(gl.get("ok"))
    gl_detail = str(gl.get("detail") or "unknown")
    renderer = gl.get("renderer")
    if renderer:
        gl_detail = f"{gl_detail} — {renderer}"
    items.append({
        "key": "opengl",
        "label": "OpenGL / GPU driver (3D & MPR rendering)",
        "status": "ok" if gl_ok else "fail",
        "detail": gl_detail,
    })

    cores = raw.get("cpu_cores")
    if not isinstance(cores, int) or cores <= 0:
        cpu = ("warning", "could not be determined")
    elif cores >= 4:
        cpu = ("ok", f"{cores} logical cores")
    elif cores >= 2:
        cpu = ("warning", f"{cores} logical cores (4+ recommended)")
    else:
        cpu = ("fail", f"{cores} logical core (2 minimum)")
    items.append({"key": "cpu", "label": "Processor (CPU)", "status": cpu[0], "detail": cpu[1]})

    ram_bytes = raw.get("ram_bytes")
    if not isinstance(ram_bytes, (int, float)) or ram_bytes <= 0:
        ram = ("warning", "could not be determined")
    else:
        gb = ram_bytes / (1024 ** 3)
        if gb >= 7.5:
            ram = ("ok", f"{gb:.1f} GB")
        elif gb >= 3.5:
            ram = ("warning", f"{gb:.1f} GB (8 GB recommended)")
        else:
            ram = ("fail", f"{gb:.1f} GB (4 GB minimum)")
    items.append({"key": "ram", "label": "Memory (RAM)", "status": ram[0], "detail": ram[1]})

    disk_bytes = raw.get("disk_free_bytes")
    if not isinstance(disk_bytes, (int, float)) or disk_bytes < 0:
        disk = ("warning", "could not be determined")
    else:
        gb = disk_bytes / (1024 ** 3)
        if gb >= 50:
            disk = ("ok", f"{gb:.0f} GB free")
        elif gb >= 10:
            disk = ("warning", f"{gb:.0f} GB free (50 GB recommended for the image cache)")
        else:
            disk = ("fail", f"{gb:.1f} GB free (10 GB minimum for the image cache)")
    items.append({"key": "disk", "label": "Free disk space (image storage)", "status": disk[0], "detail": disk[1]})

    arch = raw.get("arch")
    if isinstance(arch, dict):
        emulated = arch.get("emulated")
        proc = arch.get("process_arch") or "?"
        native = arch.get("native_arch") or "?"
        if emulated:
            plat = (
                "warning",
                f"{proc} build running under Windows-on-ARM emulation "
                f"(host {native}, Prism) — slower startup; OpenGL goes through the "
                "Microsoft D3D12 mapping layer",
            )
        elif emulated is False:
            plat = ("ok", f"native {proc}")
        else:
            plat = ("ok", f"process {proc} / host {native}")
        items.append({
            "key": "platform",
            "label": "Process architecture",
            "status": plat[0],
            "detail": plat[1],
        })

    statuses = {it["status"] for it in items}
    overall = "fail" if "fail" in statuses else ("warning" if "warning" in statuses else "ok")
    return {"items": items, "overall": overall}


# ---------------------------------------------------------------------------
# Gathering (Qt / psutil / disk — all lazy, all graceful)
# ---------------------------------------------------------------------------

def _probe_qt_opengl() -> Dict[str, Any]:
    """Create a throwaway offscreen Qt OpenGL context; return facts as a dict.

    Keys: ok, detail, major, minor, renderer, vendor. Fails GRACEFULLY where a
    VTK render window would crash natively. Never raises.
    """
    try:
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat

        fmt = QSurfaceFormat()
        fmt.setMajorVersion(MIN_GL_VERSION[0])
        fmt.setMinorVersion(MIN_GL_VERSION[1])

        ctx = QOpenGLContext()
        ctx.setFormat(fmt)
        created = bool(ctx.create())
        major = minor = 0
        renderer = vendor = None
        if created:
            eff = ctx.format()
            major, minor = int(eff.majorVersion()), int(eff.minorVersion())
            try:
                surface = QOffscreenSurface()
                surface.setFormat(ctx.format())
                surface.create()
                if surface.isValid():
                    if ctx.makeCurrent(surface):
                        try:
                            fns = ctx.functions()
                            fns.initializeOpenGLFunctions()
                            renderer = _gl_string(fns, 0x1F01)  # GL_RENDERER
                            vendor = _gl_string(fns, 0x1F00)    # GL_VENDOR
                        except Exception:
                            pass
                        ctx.doneCurrent()
                    else:
                        created = False
            except Exception:
                pass
        ok, detail = evaluate_opengl_support(created, major, minor)
        return {
            "ok": ok, "detail": detail, "major": major, "minor": minor,
            "renderer": renderer, "vendor": vendor,
        }
    except Exception as exc:  # pragma: no cover - defensive: probe must not raise
        return {"ok": False, "detail": f"OpenGL probe error: {exc!r}",
                "major": 0, "minor": 0, "renderer": None, "vendor": None}


def _gl_string(fns, enum: int) -> Optional[str]:
    try:
        val = fns.glGetString(enum)
        if val is None:
            return None
        if isinstance(val, bytes):
            return val.decode("utf-8", "replace")
        return str(val)
    except Exception:
        return None


def _gather_system_facts() -> Dict[str, Any]:
    """CPU cores / RAM / free disk on the image-storage drive. Never raises."""
    facts: Dict[str, Any] = {"cpu_cores": None, "ram_bytes": None, "disk_free_bytes": None}
    try:
        facts["cpu_cores"] = os.cpu_count()
    except Exception:
        pass
    try:
        import psutil
        facts["ram_bytes"] = int(psutil.virtual_memory().total)
    except Exception:
        pass
    try:
        import shutil
        try:
            from PacsClient.utils.data_paths import USER_DATA_ROOT as _root
        except Exception:
            _root = os.getcwd()
        facts["disk_free_bytes"] = int(shutil.disk_usage(str(_root)).free)
    except Exception:
        pass
    try:
        from PacsClient.utils.runtime_arch_log import get_runtime_architecture
        facts["arch"] = get_runtime_architecture()
    except Exception:
        pass
    return facts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_hardware_check(persist: bool = True) -> Dict[str, Any]:
    """Run the FULL hardware check now (Settings panel / forced re-test).

    Returns the persisted-shape result dict and refreshes the in-memory MPR
    gate. Fast (a few ms) but intended for on-demand use, not per-frame.
    """
    global _cached_result
    raw: Dict[str, Any] = {"opengl": _probe_qt_opengl()}
    raw.update(_gather_system_facts())
    evaluated = evaluate_hardware(raw)
    result: Dict[str, Any] = {
        "schema": PERSIST_SCHEMA,
        "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "opengl": raw["opengl"],
        "items": evaluated["items"],
        "overall": evaluated["overall"],
    }
    if persist:
        save_persisted_check(result)
    gl = raw["opengl"]
    _cached_result = (bool(gl.get("ok")), str(gl.get("detail") or "unknown"))
    logger.info(
        "[HW_CHECK] overall=%s opengl_ok=%s detail=%s renderer=%s",
        result["overall"], gl.get("ok"), gl.get("detail"), gl.get("renderer"),
    )
    return result


def opengl_preflight() -> Tuple[bool, str]:
    """The MPR gate: ``(True, detail)`` when VTK render windows are safe to build.

    Order (user directive 2026-07-07 — check once per INSTALL, never per click):
    flag off -> allow (legacy). In-memory cache -> reuse. Persisted PASS ->
    trust with ZERO probing. Persisted FAIL or nothing persisted -> probe now
    (graceful, few ms), persist, so a healthy machine never probes again and a
    machine whose driver was upgraded self-heals on the next attempt.
    """
    global _cached_result
    if not _flag_enabled():
        return True, "preflight disabled"
    if _cached_result is not None:
        return _cached_result

    persisted = load_persisted_check()
    gl = (persisted or {}).get("opengl") or {}
    if persisted is not None and gl.get("ok") is True:
        _cached_result = (True, str(gl.get("detail") or "OpenGL ok (previously verified)"))
        return _cached_result

    result = run_hardware_check(persist=True)  # also sets _cached_result
    gl = result.get("opengl") or {}
    logger.info(
        "[MPR OPENGL_PREFLIGHT] ok=%s detail=%s min_required=%d.%d (fresh probe, persisted)",
        gl.get("ok"), gl.get("detail"), MIN_GL_VERSION[0], MIN_GL_VERSION[1],
    )
    return _cached_result if _cached_result is not None else (bool(gl.get("ok")), str(gl.get("detail")))


# ---------------------------------------------------------------------------
# Test hooks
# ---------------------------------------------------------------------------

def reset_cache_for_tests() -> None:
    """Test hook: clear the cached probe result."""
    global _cached_result
    _cached_result = None


def set_persist_path_for_tests(path: Optional[str]) -> None:
    """Test hook: redirect hardware_check.json (None restores the default)."""
    global _persist_path_override
    _persist_path_override = str(path) if path is not None else None
