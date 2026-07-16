"""After a successful voice/attachment sync, the Status column refreshes itself.

THE BUG (2026-07-14): record voice → "Sync Patient Data and Close" → back on the Main
Page, the red microphone did NOT appear until the user clicked another patient and
back.

The voice is saved to local disk BEFORE upload (local-first persistence), so
``_compute_local_status_flags`` already sees it — the only reason the icon stayed
hidden was that the row's ``_local_status_cache`` entry (built before the voice
existed) was never invalidated on the sync → close → home transition.

The fix:
  * ``PatientTableWidget.refresh_status_for_study`` pops that cache and rebuilds the
    Status cell (immediate, from local disk);
  * ``HomePanelWidget.refresh_patient_status_after_sync`` also re-pulls the reception
    bundle from the SERVER (source of truth), then repaints again;
  * ``on_sync_completed`` (toolbar) calls it on the success branch, deferred past the
    tab close.

Behavioural test (cache invalidation) + source pins for the wiring. Pure-ish — the
one behavioural test uses a tiny fake table, no Qt.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


# ── behavioural: the refresh invalidates the cache and rebuilds the cell ────
class _FakeItem:
    def __init__(self, text):
        self._t = text

    def text(self):
        return self._t


class _FakeTable:
    """Minimal stand-in for the QTableWidget the method drives."""

    def __init__(self, rows, status_col, uid_col, pid_col):
        self._rows = rows            # list of {col: _FakeItem}
        self._status_col = status_col
        self._uid_col = uid_col
        self._pid_col = pid_col
        self.set_widgets = []        # (row, col, widget)

    def rowCount(self):
        return len(self._rows)

    def item(self, row, col):
        return self._rows[row].get(col)

    def setCellWidget(self, row, col, widget):
        self.set_widgets.append((row, col, widget))


def _make_widget():
    """Build a PatientTableWidget shell WITHOUT running __init__ (no Qt needed)."""
    import types
    from PacsClient.pacs.workstation_ui.home_ui import patient_table_widget as ptw

    w = ptw.PatientTableWidget.__new__(ptw.PatientTableWidget)
    w._local_status_cache = {}
    w._invalidated = []
    w._built = []

    COL = ptw.COL
    w.results_table = _FakeTable(
        rows=[{COL['study_uid']: _FakeItem('1.2.900'),
               COL['patient_id']: _FakeItem('50202')}],
        status_col=COL['status'], uid_col=COL['study_uid'], pid_col=COL['patient_id'])

    w.table_rebuild_in_progress = lambda: False
    w._invalidate_study_downloaded_cache = lambda suid: w._invalidated.append(suid)
    def _build(suid, pid):
        w._built.append((suid, pid))
        return object()
    w._build_local_status_widget = _build
    return w, COL


def test_refresh_pops_the_cache_and_rebuilds_the_status_cell():
    w, COL = _make_widget()
    # a stale cached entry from BEFORE the voice existed
    w._local_status_cache[('1.2.900', '50202')] = {
        'data': {'voice': False}, 'timestamp': 0.0}

    ok = w.refresh_status_for_study('1.2.900', '50202')

    assert ok is True
    assert ('1.2.900', '50202') not in w._local_status_cache, "stale cache must be dropped"
    assert w._invalidated == ['1.2.900']
    assert w._built == [('1.2.900', '50202')], "the Status cell must be rebuilt"
    assert w.results_table.set_widgets[0][1] == COL['status']


def test_refresh_resolves_patient_id_from_the_row_when_omitted():
    w, COL = _make_widget()
    w.refresh_status_for_study('1.2.900')           # no patient_id given
    assert w._built == [('1.2.900', '50202')]


def test_refresh_drops_every_cache_entry_for_the_study():
    w, COL = _make_widget()
    w._local_status_cache[('1.2.900', '50202')] = {'data': {}, 'timestamp': 0.0}
    w._local_status_cache[('1.2.900', '')] = {'data': {}, 'timestamp': 0.0}
    w._local_status_cache[('other', 'x')] = {'data': {}, 'timestamp': 0.0}
    w.refresh_status_for_study('1.2.900', '50202')
    assert ('1.2.900', '50202') not in w._local_status_cache
    assert ('1.2.900', '') not in w._local_status_cache
    assert ('other', 'x') in w._local_status_cache, "unrelated studies untouched"


def test_refresh_backs_off_during_a_table_rebuild(monkeypatch):
    w, COL = _make_widget()
    w.table_rebuild_in_progress = lambda: True
    from PacsClient.pacs.workstation_ui.home_ui import patient_table_widget as ptw
    scheduled = []
    monkeypatch.setattr(ptw.QTimer, "singleShot",
                        lambda ms, fn: scheduled.append(ms))
    out = w.refresh_status_for_study('1.2.900', '50202')
    assert out is False
    assert scheduled, "must retry instead of mutating a cell mid-teardown"
    assert w._built == [], "nothing rebuilt while the table is tearing down"


def test_empty_study_uid_is_a_noop():
    w, COL = _make_widget()
    assert w.refresh_status_for_study('') is False
    assert w._built == []


# ── wiring pins ─────────────────────────────────────────────────────────────
def _src(*parts) -> str:
    return (REPO.joinpath(*parts)).read_text(encoding="utf-8", errors="replace")


def test_sync_completed_refreshes_the_status_column():
    src = _src("PacsClient", "pacs", "patient_tab", "ui", "patient_ui",
               "patient_toolbar", "toolbar_manager.py")
    block = src.split("def on_sync_completed", 1)[1].split("def on_sync_failed", 1)[0]
    assert "refresh_patient_status_after_sync" in block or \
           "refresh_status_for_study" in block, (
        "the sync-success handler must refresh the patient's Status column")
    # only on the SUCCESS branch — an unconfirmed result must still bail first
    assert "_unconfirmed" in block


def test_home_panel_has_the_post_sync_entry_point():
    src = _src("PacsClient", "pacs", "workstation_ui", "home_ui", "home_panel",
               "_hp_download.py")
    assert "def refresh_patient_status_after_sync" in src
    block = src.split("def refresh_patient_status_after_sync", 1)[1].split("\n    def ", 1)[0]
    assert "refresh_status_for_study" in block, "immediate local repaint"
    assert "force=True" in block, "re-pull the reception bundle from the server"


def test_reception_repull_supports_force():
    src = _src("PacsClient", "pacs", "workstation_ui", "home_ui", "home_panel",
               "_hp_download.py")
    block = src.split("def _queue_reception_data_download_for_study", 1)[1].split("\n    def ", 1)[0]
    assert "force" in block
    assert "completed.discard(suid)" in block, (
        "force must clear the completed-guard so the study is fetched again")


def test_status_flags_still_read_voice_from_local_disk():
    """The mic is fundamentally a LOCAL flag — the voice is saved to disk before
    upload — so the local scan is what makes it appear on refresh."""
    src = _src("PacsClient", "pacs", "workstation_ui", "home_ui", "patient_table_widget.py")
    block = src.split("def _compute_local_status_flags", 1)[1].split("\n    def ", 1)[0]
    assert "_is_audio_extension" in block
    assert "voice_available = True" in block
