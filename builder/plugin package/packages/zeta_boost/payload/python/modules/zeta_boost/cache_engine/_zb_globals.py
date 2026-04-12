"""Module-level globals and utilities for ZetaBoost cache engine.

Separated to avoid circular imports -- worker mixins need _GLOBAL_DOWNLOAD_ACTIVE
(mutable global) and _set_thread_low_priority without importing widget.py.
"""
import os
import sys

# ── Global download-activity flag ──────────────────────────────────────────
# True when ANY study is currently downloading system-wide.
# All ZetaBoost warmup workers check this; when True they use the same
# generous 2-second inter-series sleep used for the active-download case,
# preventing warmup ITK pipelines from competing with the downloader and UI.
# Updated by home_ui via set_global_download_active() on download start/end.
_GLOBAL_DOWNLOAD_ACTIVE: bool = False


def set_global_download_active(active: bool) -> None:
    """Set whether ANY study is currently downloading system-wide.

    When True, ALL ZetaBoost warmup workers throttle to a 2-second
    inter-series sleep, keeping CPU and GIL free for the viewer and
    download thread even when the download is for a different patient.
    """
    global _GLOBAL_DOWNLOAD_ACTIVE
    _GLOBAL_DOWNLOAD_ACTIVE = bool(active)


def _set_thread_low_priority():
    """Lower current thread's OS scheduling priority.

    On Windows: THREAD_PRIORITY_IDLE (-15) via Win32 API.
    This is the LOWEST non-realtime priority, ensuring warmup/background
    threads never starve the UI or download threads for CPU time.
    On Linux: nice +15 via os.nice().
    Silently no-ops on failure so it never breaks the worker.
    """
    try:
        if sys.platform == 'win32':
            import ctypes
            # SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_IDLE=-15)
            handle = ctypes.windll.kernel32.GetCurrentThread()
            ctypes.windll.kernel32.SetThreadPriority(handle, -15)
        else:
            os.nice(15)
    except Exception:
        pass
