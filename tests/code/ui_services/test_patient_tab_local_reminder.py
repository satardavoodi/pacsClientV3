"""Guards for the Patient-Tab Local Physician Reminder section (2026-06-21).

The Patient-Tab "Select Status" dropdown gains a Local Physician Reminder
section that is a SECOND UI ENTRY POINT to the SAME store the Main-Page Report
popup uses (`PacsClient.utils.local_reminders`, keyed by patient_id) — NOT a
duplicate model/storage. These guards lock in:
  1. the reuse wiring is present (and the section does not roll its own store);
  2. the shared store keeps the two entry points consistent, with exactly one
     record per patient (no duplicates);
  3. the helper block is syntactically valid (without a Qt environment).
"""
import textwrap
from pathlib import Path

import PacsClient.utils.local_reminders as lr

_ROOT = Path(__file__).resolve().parents[3]
_TB = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
       / "patient_toolbar" / "toolbar_manager.py")
_DLG = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
        / "report_status_dialog.py")


def _tb_src():
    return _TB.read_text(encoding="utf-8", errors="ignore")


# ── source: reuse wiring present, not a duplicate store ──────────────────────
def test_patient_tab_reminder_section_wired():
    s = _tb_src()
    assert "def _build_patient_tab_local_reminder" in s
    assert "self._build_patient_tab_local_reminder(layout)" in s   # dropdown calls it
    assert "def _patient_tab_local_reminder_enabled" in s
    assert "AIPACS_PATIENT_TAB_LOCAL_REMINDER" in s                # kill switch (default on)


def test_patient_tab_reuses_shared_store_not_a_duplicate():
    s = _tb_src()
    i = s.index("def _build_patient_tab_local_reminder")
    seg = s[i:i + 6000]
    # uses the SAME local_reminders API + the SAME patient_id key as the Main Page
    assert "from PacsClient.utils.local_reminders import get_reminder" in seg
    assert "from PacsClient.utils.local_reminders import set_reminder" in seg
    assert "_resolve_patient_id_for_comment" in seg
    # must NOT roll its own persistence layer
    assert ".json" not in seg
    assert "open(" not in seg


def test_main_page_and_patient_tab_share_the_same_module():
    assert "from PacsClient.utils.local_reminders import" in _DLG.read_text(
        encoding="utf-8", errors="ignore")
    assert "from PacsClient.utils.local_reminders import" in _tb_src()


def test_helper_block_is_syntactically_valid():
    s = _tb_src()
    start = s.index("    def _patient_tab_local_reminder_enabled")
    end = s.index("    def _show_status_upload_dropdown")
    block = textwrap.dedent(s[start:end])
    # exec the class def — the PySide6/qtawesome imports live INSIDE method
    # bodies (run only when called), so this validates SYNTAX with no Qt env.
    ns = {}
    exec("class _C:\n" + textwrap.indent(block, "    "), ns)  # noqa: S102
    for m in ("_build_patient_tab_local_reminder", "_pt_save_reminder",
              "_pt_flush_reminder_note", "_patient_tab_local_reminder_enabled"):
        assert hasattr(ns["_C"], m), m


# ── behavioral: one shared store keeps both entry points consistent ──────────
def test_shared_store_consistency_no_duplicates(tmp_path, monkeypatch):
    import PacsClient.utils.data_paths as dp
    monkeypatch.setattr(dp, "USER_DATA_ROOT", str(tmp_path), raising=False)
    lr.reset_cache_for_tests()

    pid = "PT-123"
    # Patient Tab pins the patient …
    assert lr.set_reminder(pid, pinned=True, study_uid="S1")
    # … Main Page reads the SAME record
    r = lr.get_reminder(pid)
    assert r["pinned"] is True and r["alarm"] is False
    # Patient Tab merges alarm + note (must NOT create a second record)
    lr.set_reminder(pid, alarm=True, note="call referrer")
    r = lr.get_reminder(pid)
    assert r["pinned"] is True and r["alarm"] is True and r["note"] == "call referrer"

    import json
    store = tmp_path / "config" / "local_physician_reminders.json"
    data = json.loads(store.read_text(encoding="utf-8"))
    assert list(data.keys()) == [pid]          # exactly ONE record for the patient

    # clearing every field removes the record (matches Main Page behaviour)
    lr.set_reminder(pid, pinned=False, alarm=False, note="")
    assert lr.get_reminder(pid)["pinned"] is False
    data = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {}
    assert pid not in data
