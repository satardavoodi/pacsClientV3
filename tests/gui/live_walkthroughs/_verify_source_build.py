"""Pre-flight check shared by every tests/gui/ runner.

Refuses to drive scenarios against the frozen `aipacs.exe` /
`ai pacs viewer.exe` builds. The 2026-05-27 fixes only live in the
source build (`python.exe` launched from VS Code on main.py).

Two independent signals are checked:
    1. The project's `user_data/logs/` has at least one log file with
       an mtime newer than `recent_seconds`. The source build writes
       there at every patient-open / DM tick; the frozen build writes
       to a different path. If logs are stale, it's the frozen build.
    2. (Optional, Windows only) Look at the foreground window and
       confirm its owning process is `python.exe`.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOGS_DIR = PROJECT_ROOT / "user_data" / "logs"


class WrongBuildError(RuntimeError):
    """Raised when the running window is not the source build."""


def logs_are_fresh(recent_seconds: float = 120.0) -> tuple[bool, str]:
    """Return (ok, detail). True if any log in user_data/logs was written
    within ``recent_seconds`` ago.
    """
    candidates = [
        LOGS_DIR / "download_diagnostics.log",
        LOGS_DIR / "viewer_diagnostics.log",
        LOGS_DIR / "db_diagnostics.log",
    ]
    now = time.time()
    youngest = max(
        ((c, c.stat().st_mtime) for c in candidates if c.exists()),
        key=lambda x: x[1],
        default=(None, 0.0),
    )
    if youngest[0] is None:
        return False, f"no log files under {LOGS_DIR}"
    age = now - youngest[1]
    if age <= recent_seconds:
        return True, f"{youngest[0].name} mtime is {age:.0f}s old"
    return False, (
        f"newest log {youngest[0].name} is {age/60:.1f} min old — "
        f"the source build would be writing here right now. "
        f"You may be running the frozen aipacs.exe instead."
    )


def foreground_process_name() -> str | None:
    """Return the name of the process that owns the foreground window.
    Returns None on non-Windows or if the lookup fails.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt
        import psutil  # type: ignore

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            return None
        return psutil.Process(pid.value).name()
    except Exception:
        return None


def require_source_build(*, recent_seconds: float = 120.0,
                         require_python_exe: bool = True) -> None:
    """Raise WrongBuildError unless we're sure the running window is the
    source build.
    """
    ok, detail = logs_are_fresh(recent_seconds=recent_seconds)
    if not ok:
        raise WrongBuildError(
            f"refusing to drive scenario: {detail}.\n"
            "Launch the source build from VS Code (Play on main.py) and "
            "exercise one patient open before re-running this script."
        )
    if require_python_exe:
        name = foreground_process_name()
        if name is not None and name.lower() not in {"python.exe", "py.exe"}:
            raise WrongBuildError(
                f"foreground window owner is {name!r}, not python.exe — "
                f"that's the frozen build. Bring the source build's Python "
                f"window to the front and retry."
            )


if __name__ == "__main__":
    try:
        require_source_build()
        print("OK — source build appears to be running.")
    except WrongBuildError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(2)
