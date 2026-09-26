"""Private bounded process evidence without arguments, patient paths or secrets."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time


def system_commit():
    """Return Windows commit total/limit, which are not physical RAM usage."""
    if os.name != 'nt':
        return None
    import ctypes
    class Performance(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in
            ('CommitTotal', 'CommitLimit', 'CommitPeak', 'PhysicalTotal',
             'PhysicalAvailable', 'SystemCache', 'KernelTotal', 'KernelPaged',
             'KernelNonpaged', 'PageSize')] + [
            (name, ctypes.c_ulong) for name in ('HandleCount', 'ProcessCount', 'ThreadCount')]
    api = ctypes.WinDLL('psapi', use_last_error=True)
    api.GetPerformanceInfo.argtypes = [ctypes.POINTER(Performance), ctypes.c_ulong]
    api.GetPerformanceInfo.restype = ctypes.c_int
    value = Performance()
    value.cb = ctypes.sizeof(value)
    if not api.GetPerformanceInfo(ctypes.byref(value), ctypes.sizeof(value)):
        return None
    return value.CommitTotal * value.PageSize, value.CommitLimit * value.PageSize


class ProcessEvidence:
    def __init__(self, directory, executable):
        self.path = Path(directory) / 'process-diagnostics.jsonl'
        self.started = time.monotonic()
        self.next_sample = self.started
        self.value = {'started_utc': datetime.now(timezone.utc).isoformat(),
                      'executable': Path(executable).name, 'peak_tree_rss_bytes': 0,
                      'peak_tree_private_bytes': 0, 'minimum_commit_headroom_bytes': None,
                      'minimum_available_memory_bytes': None, 'resource_samples': 0}

    def sample(self, process):
        now = time.monotonic()
        if now < self.next_sample:
            return
        self.next_sample = now + 1
        try:
            import psutil
            parent = psutil.Process(process.pid)
            rss = private = 0
            for child in [parent, *parent.children(recursive=True)]:
                try:
                    memory = child.memory_info()
                    rss += memory.rss
                    private += getattr(memory, 'private', 0)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            available = psutil.virtual_memory().available
            previous = self.value['minimum_available_memory_bytes']
            self.value.update(pid=process.pid,
                              peak_tree_rss_bytes=max(rss, self.value['peak_tree_rss_bytes']),
                              peak_tree_private_bytes=max(private, self.value['peak_tree_private_bytes']),
                              minimum_available_memory_bytes=min(previous, available) if previous is not None else available,
                              resource_samples=self.value['resource_samples'] + 1)
            commit = system_commit()
            if commit is not None:
                headroom = max(0, commit[1] - commit[0])
                previous = self.value['minimum_commit_headroom_bytes']
                self.value['minimum_commit_headroom_bytes'] = min(previous, headroom) if previous is not None else headroom
        except (ImportError, OSError):
            pass
        except Exception:
            # Evidence collection must never change inference/cancellation behavior.
            pass

    def finish(self, returncode, outcome):
        self.value.update(elapsed_seconds=round(time.monotonic() - self.started, 3),
                          returncode=returncode, outcome=outcome)
        try:
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(self.value, allow_nan=False) + '\n')
        except OSError:
            pass
