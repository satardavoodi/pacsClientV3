"""Final process exit after application-owned cleanup has completed."""
import ctypes
from ctypes import wintypes
import os


def hard_exit(code: int = 0) -> None:
    """Exit without reentering native DLL destruction on Windows.

    This is only the last shutdown boundary, never a substitute for draining
    workers, checkpointing storage, releasing locks or flushing application logs.
    Windows os._exit still runs DLL_PROCESS_DETACH and static DLL destructors,
    which can revisit partially torn-down Qt/Shiboken wrapper registries.
    """
    if os.name != 'nt':
        os._exit(code)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    if not kernel.TerminateProcess(kernel.GetCurrentProcess(), code):
        raise ctypes.WinError(ctypes.get_last_error())
    # Successful self-termination cannot return. Do not silently continue into
    # normal DLL teardown if the native boundary behaves unexpectedly.
    raise RuntimeError('Successful process termination unexpectedly returned')
