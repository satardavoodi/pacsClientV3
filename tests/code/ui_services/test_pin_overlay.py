"""Guards for the persistent pinned-patient overlay on the Main-Page list (2026-06-21).

A PINNED patient must stay visible in the Search Patients list even when the
current query would exclude them (e.g. yesterday's patient after a new search),
survive app restart, and never duplicate a patient already in the results. The
overlay reuses the local_reminders store (a `row` snapshot per pinned patient),
is local-only, and dedups by patient_id. These guards cover the storage/dedup
logic (pure) + the Main-Page wiring (source pins).
"""
from pathlib import Path

import PacsClient.utils.local_reminders as lr

_ROOT = Path(__file__).resolve().parents[3]
_PT = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
       / "patient_table_widget.py")


def _patch_store(tmp_path, monkeypatch):
    import PacsClient.utils.data_paths as dp
    monkeypatch.setattr(dp, "USER_DATA_ROOT", str(tmp_path), raising=False)
    lr.reset_cache_for_tests()


# ── storage: row snapshot is the overlay source ──────────────────────────────
def test_row_snapshot_stored_and_listed(tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    pid = "P1"
    lr.set_reminder(pid, pinned=True, row={
        "patient_name": "DOE^J", "patient_id": pid, "modality": "MR",
        "date": "2026-06-20"})
    rows = lr.get_pinned_rows()
    assert pid in rows and rows[pid]["modality"] == "MR"
    assert lr.get_reminder(pid)["pinned"] is True       # pin state unaffected


def test_pinned_without_snapshot_is_not_overlaid(tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    lr.set_reminder("P2", pinned=True)                  # no row snapshot
    assert "P2" not in lr.get_pinned_rows()


def test_unpin_removes_overlay_record(tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    pid = "P3"
    lr.set_reminder(pid, pinned=True, row={"patient_id": pid, "patient_name": "X"})
    assert pid in lr.get_pinned_rows()
    lr.set_reminder(pid, pinned=False)                  # explicit unpin
    assert pid not in lr.get_pinned_rows()
    assert lr.get_reminder(pid)["pinned"] is False


def test_overlay_persists_across_restart(tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    pid = "P4"
    lr.set_reminder(pid, pinned=True, row={
        "patient_id": pid, "patient_name": "Y", "modality": "CT"})
    lr.reset_cache_for_tests()                          # simulate app restart (reload from disk)
    rows = lr.get_pinned_rows()
    assert pid in rows and rows[pid]["modality"] == "CT"


def test_overlay_dedups_against_present_patients(tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    for pid in ("A", "B", "C"):
        lr.set_reminder(pid, pinned=True, row={"patient_id": pid, "patient_name": pid})
    pinned = lr.get_pinned_rows()
    present = {"B"}                                     # B already in live results
    missing = {pid for pid in pinned if pid not in present}
    assert missing == {"A", "C"}                        # only absent pinned patients overlaid


# ── source pins: Main-Page wiring ────────────────────────────────────────────
def test_patient_table_overlay_wired():
    s = _PT.read_text(encoding="utf-8", errors="ignore")
    assert "def _apply_pinned_overlay" in s
    assert "def _remove_provisional_pin_overlay_row" in s
    assert "def _arm_pin_overlay_refresh" in s
    assert "_PIN_OVERLAY_ROLE" in s
    assert "AIPACS_PIN_OVERLAY" in s
    # reuses the SHARED local store (no duplicate system)
    assert "from PacsClient.utils.local_reminders import get_pinned_rows" in s
    assert "row=self._pin_snapshot_from_kwargs(kwargs)" in s
    # a result for a pinned patient is deduped IN PLACE (kept fixed at the top)
    assert "self._find_pinned_row_for_patient(patient_id)" in s
    assert "pid not in present" in s
    # overlay re-armed after a new search clears the table
    assert "_arm_pin_overlay_refresh()" in s


def test_overlay_section_is_local_only():
    s = _PT.read_text(encoding="utf-8", errors="ignore")
    i = s.index("def _apply_pinned_overlay")
    seg = s[i:i + 2500]
    for bad in ("send_request", "report_status_service", "GetPatient", "socket_client"):
        assert bad not in seg, bad


# ── Fix 2 (2026-06-22): pinned-top enforcement + immediate float + click re-assert ──
def test_pinned_top_enforcement_wired():
    s = _PT.read_text(encoding="utf-8", errors="ignore")
    # present pinned rows (not just absent ones) get the boost → they float (bug 2.1)
    assert "def _enforce_pin_boost_on_rows" in s
    assert "self._enforce_pin_boost_on_rows(pinned_ids)" in s
    # gated on ANY pinned existing (or a leftover boosted row) → no-op for
    # unpinned users, but still normalises the last-unpinned row.
    assert "get_pinned_patient_ids" in s
    assert "if not pinned_ids and not self._any_row_boosted()" in s
    # the old early return that skipped present-pinned must be gone
    assert "if not missing:\n            return" not in s
    # pin floats IMMEDIATELY (2.1)
    assert "self._apply_pinned_overlay()" in s
    # clicking re-asserts pinned-top (2.2)
    i = s.index("def _emit_patient_selection_now")
    assert "_arm_pin_overlay_refresh()" in s[i:i + 1500]


def test_stable_pinned_section_wired():
    """Polish (2026-06-22): pinned rows form a STABLE top section — clear_table
    keeps them, results dedup in place (no jump/flicker), and a subtle tint
    marks the section."""
    s = _PT.read_text(encoding="utf-8", errors="ignore")
    # clear_table preserves pinned rows instead of wiping the whole table
    ci = s.index("def clear_table")
    seg = s[ci:ci + 1400]
    assert "get_pinned_patient_ids" in seg
    assert "removeRow(row)" in seg            # only non-pinned rows removed
    assert "pinned_rows_kept" in seg
    # in-place dedup keeps the pinned row fixed (refresh, not re-insert)
    assert "def _find_pinned_row_for_patient" in s
    assert "self._refresh_existing_study_row(_pinned_row, kwargs)" in s
    # subtle visual separation for the pinned section
    assert "def _apply_pinned_row_tint" in s
