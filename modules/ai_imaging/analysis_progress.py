"""Thread-safe completed-work snapshots, independent of Qt and patient identity."""
from threading import Lock


class AnalysisProgress:
    def __init__(self):
        self._lock = Lock()
        self._value = None

    def update(self, completed, total, stage):
        if total <= 0 or not 0 <= completed <= total:
            raise ValueError('Invalid completed-work count.')
        with self._lock:
            self._value = (completed, total, str(stage))

    def snapshot(self):
        with self._lock:
            return self._value


def display_progress(bar, label, progress):
    value = progress.snapshot() if progress is not None else None
    if value is None:
        bar.setRange(0, 0)
        return False
    completed, total, stage = value
    percent = int(100 * completed / total)
    bar.setRange(0, 100)
    bar.setValue(percent)
    bar.setFormat('%p% of stages completed')
    label.setText(f'{stage} | {completed}/{total} stages completed; {total-completed} remaining. '
                  'Stages vary in duration; remaining time is not yet available.')
    return True
