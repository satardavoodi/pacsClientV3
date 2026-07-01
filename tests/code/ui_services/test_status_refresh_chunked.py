"""Guard test for P1.2 — cooperative chunking of the download-status refresh.

`refresh_download_statuses` used to scan every visible study's download state on the GUI
thread in one synchronous loop (each row does check_study_complete -> build_local_manifest,
a disk walk), which froze the event loop. P1.2 processes the rows in small chunks that yield
to the Qt event loop between studies — still entirely on the main thread (no worker threads,
no cache races); only the *scheduling* changes.

Source-pins guard the real edit (no PySide6/QApplication needed). A mirror-behavioral test
reproduces the exact chunk-driver algorithm and proves it processes every study once, in
order, honors the chunk size, and cancels a stale chain when a newer refresh supersedes it
(constructing a real PatientTableWidget needs a QApplication, so the algorithm is mirrored).
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PTW = REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "patient_table_widget.py"


def _src() -> str:
    return PTW.read_text(encoding="utf-8", errors="ignore")


def test_flag_default_on_and_dispatch():
    s = _src()
    assert 'os.getenv("AIPACS_STATUS_REFRESH_CHUNKED", "1")' in s, "chunking flag must default ON"
    assert "self._refresh_statuses_chunked(study_uids, 0, self._status_refresh_token)" in s


def test_chunked_helper_and_token_guard():
    s = _src()
    assert "def _refresh_statuses_chunked(self, study_uids, index, token):" in s
    # supersede guard: a newer refresh cancels the stale chain
    assert "if token != getattr(self, '_status_refresh_token', 0):" in s
    # yields to the event loop between chunks
    assert "QTimer.singleShot(0, lambda: self._refresh_statuses_chunked(study_uids, end, token))" in s
    assert 'os.getenv("AIPACS_STATUS_REFRESH_CHUNK", "2")' in s


def test_kill_switch_preserves_synchronous_loop():
    s = _src()
    # flag off -> the original synchronous per-row loop must still be present
    start = s.index('os.getenv("AIPACS_STATUS_REFRESH_CHUNKED"')
    region = s[start:start + 1600]
    assert "else:" in region
    assert "self.update_study_download_status(study_uid)" in region
    assert "Refreshed download statuses for" in region


# --- mirror-behavioral: exact algorithm of _refresh_statuses_chunked -----------------

class _Mirror:
    """Standalone re-implementation of the driver (a real widget needs a QApplication)."""

    def __init__(self):
        self._status_refresh_token = 0
        self.processed = []
        self._timers = []
        self.done = False

    def update_study_download_status(self, uid):
        self.processed.append(uid)

    def _refresh_statuses_chunked(self, study_uids, index, token, chunk=2):
        if token != self._status_refresh_token:
            return
        end = min(index + chunk, len(study_uids))
        for i in range(index, end):
            self.update_study_download_status(study_uids[i])
        if end < len(study_uids):
            self._timers.append(lambda: self._refresh_statuses_chunked(study_uids, end, token, chunk))
        else:
            self.done = True

    def _drain(self):
        while self._timers:
            self._timers.pop(0)()


def test_mirror_processes_every_study_once_in_order():
    m = _Mirror()
    uids = [f"u{i}" for i in range(7)]
    m._status_refresh_token = 1
    m._refresh_statuses_chunked(uids, 0, 1, chunk=2)
    m._drain()
    assert m.processed == uids
    assert m.done


def test_mirror_token_supersede_cancels_stale_chain():
    m = _Mirror()
    uids = [f"u{i}" for i in range(7)]
    m._status_refresh_token = 1
    m._refresh_statuses_chunked(uids, 0, 1, chunk=2)  # processes u0,u1; schedules next
    m._status_refresh_token = 2                        # a newer refresh starts
    m._drain()
    assert m.processed == ["u0", "u1"]                 # stale chain stopped
    assert not m.done
