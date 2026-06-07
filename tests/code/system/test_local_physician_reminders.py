"""Guards: local-only physician reminders (pin / alarm / note), 2026-06-06.

Contract:
  - Stored ONLY in a local user_data JSON; the module performs no network
    I/O of any kind (source-pinned).
  - Keyed by patient_id (trimmed); empty entries are pruned.
  - Report popup gains a clearly-labelled local section saved on ANY close.
  - Patient list: indicators on the name cell; pinned patients get a date
    sort-key boost so they lead the default (date-desc) search ordering.
"""
import inspect
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PacsClient.utils import local_reminders  # noqa: E402


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    store = tmp_path / "local_physician_reminders.json"
    monkeypatch.setattr(local_reminders, "_store_path", lambda: store)
    local_reminders.reset_cache_for_tests()
    yield store
    local_reminders.reset_cache_for_tests()


def test_round_trip_and_defaults(tmp_store):
    assert local_reminders.get_reminder("44820") == {
        "pinned": False, "alarm": False, "note": "", "study_uid": "", "updated_at": "",
    }
    assert local_reminders.set_reminder(
        "44820", pinned=True, alarm=True, note="check prior CT", study_uid="1.2.3",
    )
    r = local_reminders.get_reminder(" 44820 ")  # key normalization
    assert r["pinned"] and r["alarm"] and r["note"] == "check prior CT"
    assert r["study_uid"] == "1.2.3" and r["updated_at"]
    assert local_reminders.has_flags("44820")

    # persisted on disk, valid JSON
    data = json.loads(tmp_store.read_text(encoding="utf-8"))
    assert "44820" in data


def test_no_cross_patient_mixing(tmp_store):
    local_reminders.set_reminder("1", note="note for one")
    local_reminders.set_reminder("2", pinned=True)
    assert local_reminders.get_reminder("1")["note"] == "note for one"
    assert not local_reminders.get_reminder("1")["pinned"]
    assert local_reminders.get_reminder("2")["pinned"]
    assert local_reminders.get_reminder("2")["note"] == ""


def test_all_default_entry_is_pruned(tmp_store):
    local_reminders.set_reminder("3", pinned=True)
    local_reminders.set_reminder("3", pinned=False, alarm=False, note="")
    assert not local_reminders.has_flags("3")
    data = json.loads(tmp_store.read_text(encoding="utf-8"))
    assert "3" not in data


def test_merge_updates_keep_other_fields(tmp_store):
    local_reminders.set_reminder("4", note="keep me")
    local_reminders.set_reminder("4", pinned=True)  # note untouched
    r = local_reminders.get_reminder("4")
    assert r["pinned"] and r["note"] == "keep me"


def test_storage_module_is_strictly_local():
    src = inspect.getsource(local_reminders)
    for forbidden in ("requests", "socket_client", "send_request", "http", "urllib"):
        assert forbidden not in src, f"local reminders must never touch the network ({forbidden})"


# ------------------------------------------------------------ wiring pins ----

def test_dialog_has_local_section_saved_on_any_close():
    from PacsClient.pacs.workstation_ui.home_ui.report_status_dialog import ReportStatusDialog

    src = inspect.getsource(ReportStatusDialog)
    assert "Local Physician Reminder" in src
    assert "Stored only on this workstation" in src
    assert "_save_local_reminder_if_changed" in inspect.getsource(ReportStatusDialog.done), (
        "local section must be saved on ANY dialog close (Apply or Cancel)"
    )
    # local save path must call the local store, not the server
    save_src = inspect.getsource(ReportStatusDialog._save_local_reminder_if_changed)
    assert "local_reminders" in save_src
    assert "statusChanged" not in save_src  # never rides the server-status signal


def test_table_applies_indicators_and_pin_sort_boost():
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import PatientTableWidget

    src = inspect.getsource(PatientTableWidget.add_patient_data)
    assert "_decorate_name_item_with_reminder" in src
    assert "_PIN_SORT_BOOST" in src
    assert PatientTableWidget._PIN_SORT_BOOST >= 10 ** 10  # dwarfs yyyymmdd keys

    deco = inspect.getsource(PatientTableWidget._decorate_name_item_with_reminder)
    for icon in ("exclamation-triangle", "thumbtack", "sticky-note"):
        assert icon in deco
    assert "Local reminder" in deco  # labelled tooltip block
