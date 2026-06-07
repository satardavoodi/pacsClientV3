"""Guards: the Refresh button also refreshes the Report column (2026-06-06).

One refresh action now synchronizes BOTH columns with the server:
  - Status (download state)            — pre-existing path, unchanged
  - Report (workflow status + physician) — new: clears caches, hydrates
    every visible row from the Reception API in bounded background workers,
    marshals updates through queued signals.

Also pins the Reception→app status vocabulary mapping (awaiting approval /
secretary / doctor, reported, confirmed, ...) and its conservative
unknown→'' contract (never clobber a row's status with a guess).
"""
import inspect
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# --------------------------------------------------- status word mapping ----

def _mixin():
    from PacsClient.pacs.workstation_ui.home_ui.home_panel._hp_search import _HPSearchMixin
    return _HPSearchMixin


def test_reception_status_words_map_to_app_vocabulary():
    extract = _mixin()._extract_report_status_from_reception_payload

    cases = {
        'pending': 'pending',
        'Awaiting Approval': 'awaiting_approval',
        'awaiting-secretary': 'awaiting_secretary_approval',
        'awaiting_doctor': 'awaiting_physician_approval',
        'awaiting physician approval': 'awaiting_physician_approval',
        'Reported': 'physician_approved',
        'secretary_approved': 'secretary_approved',
        'Confirmed': 'completed',
        'approved': 'completed',
        'completed': 'completed',
        'archived': 'archived',
    }
    for raw, expected in cases.items():
        assert extract({'report': {'status': raw}}) == expected, raw


def test_reception_status_unknown_or_missing_is_empty():
    extract = _mixin()._extract_report_status_from_reception_payload
    assert extract({'report': {'status': 'some_new_server_state'}}) == ''
    assert extract({'report': {}}) == ''
    assert extract({}) == ''
    assert extract(None) == ''


def test_reception_status_approval_evidence_fallback():
    extract = _mixin()._extract_report_status_from_reception_payload
    assert extract({'report': {'approvedBy': 'dr.x'}}) == 'completed'
    assert extract({'report': {'approved_at': '2026-06-06'}}) == 'completed'


def test_status_checked_on_payload_root_too():
    extract = _mixin()._extract_report_status_from_reception_payload
    assert extract({'report_status': 'awaiting_secretary'}) == 'awaiting_secretary_approval'


# ------------------------------------------------------- wiring (pinned) ----

def test_refresh_button_triggers_report_refresh():
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import PatientTableWidget

    src = inspect.getsource(PatientTableWidget.refresh_download_statuses)
    assert "_report_status_cache" in src and ".clear()" in src
    assert "reportRefreshRequested.emit()" in src


def test_panel_hydrates_all_rows_and_clears_physician_cache():
    mixin = _mixin()
    src = inspect.getsource(mixin._refresh_report_column_from_server)
    assert "collect_all_rows_for_report_refresh" in src
    assert "_reporting_physician_cache" in src
    assert "_queue_reporting_physician_hydration" in src


def test_worker_emits_status_through_queued_signal():
    mixin = _mixin()
    src = inspect.getsource(mixin._queue_reporting_physician_hydration)
    assert "reportStatusResolved.emit" in src
    assert "_extract_report_status_from_reception_payload" in src


def test_table_signal_connected_to_status_updater():
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import PatientTableWidget

    src = inspect.getsource(PatientTableWidget)
    assert "reportStatusResolved = Signal(str, str)" in src
    assert "self.reportStatusResolved.connect(self._update_report_status_in_table)" in src


def test_collector_returns_every_row_shape():
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import PatientTableWidget

    src = inspect.getsource(PatientTableWidget.collect_all_rows_for_report_refresh)
    assert "rowCount()" in src
    assert "COL['study_uid']" in src and "COL['patient_id']" in src
