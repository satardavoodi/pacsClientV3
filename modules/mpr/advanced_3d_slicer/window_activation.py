"""Allow only the explicitly requested viewer process to take foreground focus."""
import os


def allow_viewer_foreground(pid):
    if os.name != "nt" or not isinstance(pid, int) or pid <= 0:
        return False
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    user32.AllowSetForegroundWindow.restype = wintypes.BOOL
    return bool(user32.AllowSetForegroundWindow(pid))
