"""OPT-50 (2026-08-03) — Local patient-list render cost.

The Local list was O(N^2) on the GUI thread and unusable past ~2000 studies.
Four independent quadratic/per-row costs, all locked out here:

  1. `add_patient_data`'s per-study dedup scanned EVERY existing row for EVERY
     insert (~2 M item() lookups at 2000 rows) -> study_uid presence set.
  2. Two SQLite connections PER ROW (visited flag + Imported-On stamp)
     -> two batched queries for the whole result set.
  3. `_finalize_bulk_insert_ui` ran a full-table anti-alias + sort + count after
     EVERY 40-row batch (~50x) -> incremental anti-alias + one debounced settle
     sort that honours the ACTIVE sort column.
  4. `_assign_icon_state` / `_apply_report_status_display` re-read two JSON
     stores three times per row, and `report_status_for_reception` scanned the
     whole table per row -> mtime-guarded store caches + a render-pass memo.

Measured (tests/bench/bench_local_patient_list.py, 2000 studies):
    full load 42.7 s -> 13.9 s   worst GUI block 1139 ms -> 271 ms
    db_calls 4000 -> 1           dedup scan rows 1 999 000 -> 0

`patient_table_widget.py` imports Qt at module scope and the widget is expensive
to construct, so the widget-level tests bind the REAL unbound methods onto a
light stub (the established pattern in this suite) and the rest is source-pinned.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found")


def _widget_src() -> str:
    return (_repo_root() / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
            / "patient_table_widget.py").read_text(encoding="utf-8")


def _search_src() -> str:
    return (_repo_root() / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
            / "home_search_service.py").read_text(encoding="utf-8")


def _method(src: str, name: str) -> str:
    i = src.find(f"def {name}(")
    assert i != -1, f"method {name} not found"
    body = src[i:]
    nxt = body.find("\n    def ", 10)
    return body[:nxt] if nxt != -1 else body


def _isolate_db(tmp_path, monkeypatch):
    """Redirect the DB to a temp file (DB test-isolation rule: patch
    data_paths.DATABASE_FILE + clear the connection pool)."""
    dbfile = tmp_path / "dicom.db"
    import PacsClient.utils.data_paths as dp
    monkeypatch.setattr(dp, "DATABASE_FILE", str(dbfile), raising=False)
    import database._pool as pool
    try:
        with pool._pool_lock:
            pool._connection_pool.clear()
    except Exception:
        pool._connection_pool.clear()
    return dbfile


# ── 1. Data layer: batched visited lookup + the new indexes ──────────────────

def test_get_existing_patient_ids_returns_only_known(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from database import dicom_db
    dicom_db.init_database()
    with dicom_db.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO patients (patient_id, patient_name) VALUES ('P1','A')")
        cur.execute("INSERT INTO patients (patient_id, patient_name) VALUES ('P2','B')")
        conn.commit()

    got = dicom_db.get_existing_patient_ids(["P1", "P2", "P404", "", None])
    assert got == {"P1", "P2"}
    # Empty / bad input must never raise and never claim a match.
    assert dicom_db.get_existing_patient_ids([]) == set()
    assert dicom_db.get_existing_patient_ids(None) == set()


def test_get_existing_patient_ids_chunks_past_sqlite_var_limit(tmp_path, monkeypatch):
    """>999 ids must not blow SQLite's bound-variable limit."""
    _isolate_db(tmp_path, monkeypatch)
    from database import dicom_db
    dicom_db.init_database()
    with dicom_db.get_db_connection() as conn:
        cur = conn.cursor()
        for i in range(1200):
            cur.execute("INSERT INTO patients (patient_id, patient_name) VALUES (?,?)",
                        (f"P{i}", f"NAME{i}"))
        conn.commit()
    got = dicom_db.get_existing_patient_ids([f"P{i}" for i in range(1200)])
    assert len(got) == 1200


def test_patient_list_query_indexes_exist(tmp_path, monkeypatch):
    """The Local search joins on patient_fk and filters on study_date /
    imported_at / modality — none of which was indexed before OPT-50."""
    _isolate_db(tmp_path, monkeypatch)
    from database import dicom_db
    dicom_db.init_database()
    with dicom_db.get_db_connection() as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    for expected in ("idx_studies_patient_fk", "idx_studies_study_date",
                     "idx_studies_imported_at", "idx_studies_modality",
                     "idx_patients_patient_name"):
        assert expected in names, f"missing index {expected}"


def test_init_database_is_idempotent(tmp_path, monkeypatch):
    """IF NOT EXISTS — a second startup must not raise."""
    _isolate_db(tmp_path, monkeypatch)
    from database import dicom_db
    dicom_db.init_database()
    dicom_db.init_database()


# ── 2. study_uid presence set (kills the O(N^2) dedup scan) ──────────────────

def _P():
    pytest.importorskip("PySide6")
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import PatientTableWidget
    return PatientTableWidget


def _fake_table(uid_by_row=None):
    """A MagicMock QTableWidget whose study_uid column returns given texts."""
    from unittest.mock import MagicMock
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import COL
    uid_by_row = uid_by_row or {}
    t = MagicMock()
    t.rowCount.return_value = len(uid_by_row)

    def _item(row, col):
        if col != COL['study_uid'] or row not in uid_by_row:
            return None
        it = MagicMock()
        it.text.return_value = uid_by_row[row]
        return it

    t.item.side_effect = _item
    return t


def _uid_stub(uid_by_row=None):
    P = _P()

    class _S:
        _uid_index_enabled = staticmethod(P._uid_index_enabled)
        _uid_set = P._uid_set
        _may_have_study_uid = P._may_have_study_uid
        _note_study_uid_present = P._note_study_uid_present
        _rebuild_study_uid_index = P._rebuild_study_uid_index

        def __init__(self):
            self.results_table = _fake_table(uid_by_row)

    return _S()


def test_unseen_uid_skips_the_row_scan():
    s = _uid_stub()
    assert s._may_have_study_uid("1.2.3") is False
    # a False answer means add_patient_data never enters the scan loop at all
    assert s.results_table.item.call_count == 0


def test_noted_uid_triggers_the_scan():
    s = _uid_stub()
    s._note_study_uid_present("1.2.3")
    assert s._may_have_study_uid("1.2.3") is True
    assert s._may_have_study_uid("9.9.9") is False


def test_kill_switch_restores_always_scan(monkeypatch):
    monkeypatch.setenv("AIPACS_LIST_UID_INDEX", "0")
    s = _uid_stub()
    # legacy behaviour: every insert scans, regardless of the set
    assert s._may_have_study_uid("never-seen") is True


def test_rebuild_recovers_the_set_from_surviving_rows():
    """clear_table KEEPS pinned rows, so the set is rebuilt, not emptied."""
    s = _uid_stub({0: "pinned.1", 1: "pinned.2"})
    s._note_study_uid_present("gone.1")
    s._rebuild_study_uid_index()
    assert s._may_have_study_uid("pinned.1") is True
    assert s._may_have_study_uid("pinned.2") is True
    assert s._may_have_study_uid("gone.1") is False


def test_add_patient_data_guards_the_scan_and_registers_the_uid():
    src = _widget_src()
    fn = _method(src, "add_patient_data")
    assert "if incoming_study_uid and self._may_have_study_uid(incoming_study_uid):" in fn
    assert "self._note_study_uid_present(incoming_study_uid)" in fn


# ── 3. Batched DB prime replaces the two per-row SQLite round-trips ──────────

def test_visited_prime_answers_without_touching_the_db(monkeypatch):
    P = _P()
    from PacsClient.pacs.workstation_ui.home_ui import patient_table_widget as ptw

    calls = []
    monkeypatch.setattr(ptw, "find_patient_pk", lambda pid: calls.append(pid))

    class _S:
        _db_prefetch_enabled = staticmethod(P._db_prefetch_enabled)
        prime_visited_patient_ids = P.prime_visited_patient_ids
        check_patient_visited = P.check_patient_visited

    s = _S()
    s.prime_visited_patient_ids({"P1", "P2"})
    assert s.check_patient_visited("P1") is True
    assert s.check_patient_visited("P404") is False
    assert calls == [], "primed lookups must not hit the database"


def test_visited_falls_back_to_the_db_when_not_primed(monkeypatch):
    P = _P()
    from PacsClient.pacs.workstation_ui.home_ui import patient_table_widget as ptw
    calls = []

    def _find(pid):
        calls.append(pid)
        return 7 if pid == "P1" else None

    monkeypatch.setattr(ptw, "find_patient_pk", _find)

    class _S:
        _db_prefetch_enabled = staticmethod(P._db_prefetch_enabled)
        prime_visited_patient_ids = P.prime_visited_patient_ids
        check_patient_visited = P.check_patient_visited

    s = _S()
    s.prime_visited_patient_ids(None)          # explicitly un-primed
    assert s.check_patient_visited("P1") is True
    assert s.check_patient_visited("P9") is False
    assert calls == ["P1", "P9"], "un-primed callers keep the legacy DB lookup"


def test_visited_kill_switch_forces_the_db_lookup(monkeypatch):
    P = _P()
    from PacsClient.pacs.workstation_ui.home_ui import patient_table_widget as ptw
    monkeypatch.setenv("AIPACS_LIST_DB_PREFETCH", "0")
    calls = []
    monkeypatch.setattr(ptw, "find_patient_pk", lambda pid: calls.append(pid))

    class _S:
        _db_prefetch_enabled = staticmethod(P._db_prefetch_enabled)
        prime_visited_patient_ids = P.prime_visited_patient_ids
        check_patient_visited = P.check_patient_visited

    s = _S()
    s.prime_visited_patient_ids({"P1"})
    s.check_patient_visited("P1")
    assert calls == ["P1"]


def test_imported_on_prime_records_misses_so_no_row_requeries(monkeypatch):
    """A study with no imported_at must be cached as "" — otherwise every row
    without a stamp re-issues the query it was meant to replace."""
    P = _P()
    from database import dicom_db

    calls = []
    monkeypatch.setattr(dicom_db, "get_imported_at_map",
                        lambda uids: calls.append(list(uids)) or {})

    class _S:
        prime_imported_on_cache = P.prime_imported_on_cache
        _resolve_imported_on = P._resolve_imported_on
        _format_imported_on = staticmethod(P._format_imported_on)
        _IMPORTED_ON_EMPTY = P._IMPORTED_ON_EMPTY

    s = _S()
    s.prime_imported_on_cache(["u1", "u2"], {"u1": "2026-08-01 10:30:00"})

    assert s._resolve_imported_on(["u1"]) == ("2026-08-01  10:30", "2026-08-01 10:30:00")
    assert s._resolve_imported_on(["u2"]) == (P._IMPORTED_ON_EMPTY, "")
    assert calls == [], "primed UIDs must not re-query, including the misses"

    # a UID that was never primed still resolves through the DB (no regression)
    s._resolve_imported_on(["u3"])
    assert calls == [["u3"]]


# ── 4. Per-batch whole-table work -> one settle pass ────────────────────────

def _settle_stub(active_col=None, sort_states=None, cursor=0, total=0):
    P = _P()

    class _S:
        _STREAM_SETTLE_MS = P._STREAM_SETTLE_MS
        _batch_finalize_enabled = staticmethod(P._batch_finalize_enabled)
        _stream_in_flight = P._stream_in_flight
        _on_stream_settled = P._on_stream_settled
        _end_report_status_memo = P._end_report_status_memo

        def __init__(self):
            self._prog_cursor = cursor
            self._prog_total = total
            self._active_sort_col = active_col
            self._sort_states = sort_states or {}
            self.sorted_with = []
            self.rearmed = 0

        def _arm_stream_settle_sort(self):
            self.rearmed += 1

        def _programmatic_sort(self, col, order):
            self.sorted_with.append((col, order))

        def _update_results_count(self):
            pass

    return _S()


def test_settle_sort_honours_the_active_sort_column():
    """THE BUG: the old per-batch code only sorted when NO user sort was active,
    so rows streamed in behind 'sort by Imported On' were appended unsorted."""
    from PySide6.QtCore import Qt
    s = _settle_stub(active_col=15, sort_states={15: 2}, cursor=100, total=100)
    s._on_stream_settled()
    assert s.sorted_with == [(15, Qt.DescendingOrder)]

    s = _settle_stub(active_col=15, sort_states={15: 1}, cursor=100, total=100)
    s._on_stream_settled()
    assert s.sorted_with == [(15, Qt.AscendingOrder)]


def test_settle_sort_defaults_to_date_descending_when_no_user_sort():
    from PySide6.QtCore import Qt
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import COL
    s = _settle_stub(active_col=None, cursor=50, total=50)
    s._on_stream_settled()
    assert s.sorted_with == [(COL['date'], Qt.DescendingOrder)]


def test_settle_pass_waits_while_rows_are_still_streaming():
    s = _settle_stub(active_col=None, cursor=40, total=2000)
    s._on_stream_settled()
    assert s.sorted_with == [], "must not sort a half-filled table"
    assert s.rearmed == 1, "must re-arm until the stream finishes"


def test_finalize_defers_sort_and_count_while_streaming():
    src = _widget_src()
    fn = _method(src, "_finalize_bulk_insert_ui")
    assert "_streaming = self._batch_finalize_enabled() and self._stream_in_flight()" in fn
    assert "if not _streaming:\n            self._update_results_count()" in fn
    assert "self._arm_stream_settle_sort()" in fn
    # the legacy per-batch default sort survives for the NON-streaming path
    assert "elif getattr(self, '_active_sort_col', None) is None:" in fn


def test_anti_aliasing_rows_touches_only_the_given_range():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem
    from PySide6.QtGui import QFont
    from PacsClient.utils.font_manager import apply_anti_aliasing_to_rows

    QApplication.instance() or QApplication([])
    t = QTableWidget(4, 2)
    for r in range(4):
        for c in range(2):
            it = QTableWidgetItem(f"{r}-{c}")
            f = it.font()
            f.setStyleStrategy(QFont.PreferDefault)
            it.setFont(f)
            t.setItem(r, c, it)

    assert apply_anti_aliasing_to_rows(t, 2, 4) is True
    assert t.item(0, 0).font().styleStrategy() == QFont.PreferDefault
    assert t.item(1, 0).font().styleStrategy() == QFont.PreferDefault
    assert t.item(2, 0).font().styleStrategy() == QFont.PreferAntialias
    assert t.item(3, 1).font().styleStrategy() == QFont.PreferAntialias
    # out-of-range / inverted requests are safe no-ops
    assert apply_anti_aliasing_to_rows(t, 4, 4) is True
    assert apply_anti_aliasing_to_rows(t, 3, 1) is True


# ── 5. report_status_for_reception render-pass memo ─────────────────────────

def _report_stub(rows=None):
    """rows: {row_index: (patient_id, report_status)}"""
    from unittest.mock import MagicMock
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import COL
    P = _P()
    rows = rows or {}

    class _S:
        _report_memo_enabled = staticmethod(P._report_memo_enabled)
        _begin_report_status_memo = P._begin_report_status_memo
        _end_report_status_memo = P._end_report_status_memo
        report_status_for_reception = P.report_status_for_reception

        def __init__(self):
            t = MagicMock()
            t.rowCount.return_value = len(rows)
            self.scans = []

            def _item(row, col):
                self.scans.append(row)
                if col != COL['patient_id'] or row not in rows:
                    return None
                it = MagicMock()
                it.text.return_value = rows[row][0]
                return it

            def _cell(row, col):
                w = MagicMock()
                w.report_status = rows.get(row, ("", ""))[1]
                return w

            t.item.side_effect = _item
            t.cellWidget.side_effect = _cell
            self.results_table = t

    return _S()


def test_report_status_memo_serves_repeat_lookups_without_scanning():
    s = _report_stub({0: ("P1", "completed")})
    s._begin_report_status_memo()
    assert s.report_status_for_reception("P1") == "completed"   # scan (miss)
    n = len(s.scans)
    assert s.report_status_for_reception("P1") == "completed"   # memo hit
    assert len(s.scans) == n, "a memo hit must not re-scan the table"


def test_report_status_memo_never_caches_an_empty_scan():
    """The FIRST row of a patient asks before its own row exists; caching that ""
    would then be served to the patient's later rows."""
    s = _report_stub({})                       # nothing in the table yet
    s._begin_report_status_memo()
    assert s.report_status_for_reception("P1") == ""
    # the insert path records the real value with setdefault
    s._report_status_by_reception.setdefault("P1", "pending")
    assert s.report_status_for_reception("P1") == "pending"


def test_report_status_memo_setdefault_keeps_the_first_row():
    s = _report_stub({})
    s._begin_report_status_memo()
    s._report_status_by_reception.setdefault("P1", "completed")
    s._report_status_by_reception.setdefault("P1", "pending")   # 2nd study, ignored
    assert s.report_status_for_reception("P1") == "completed"


def test_report_status_is_live_again_once_the_memo_is_disarmed():
    s = _report_stub({0: ("P1", "completed")})
    s._begin_report_status_memo()
    s.report_status_for_reception("P1")
    s._end_report_status_memo()
    n = len(s.scans)
    assert s.report_status_for_reception("P1") == "completed"
    assert len(s.scans) > n, "outside a render pass every call must read the table"


def test_report_memo_kill_switch(monkeypatch):
    monkeypatch.setenv("AIPACS_LIST_REPORT_MEMO", "0")
    s = _report_stub({0: ("P1", "completed")})
    s._begin_report_status_memo()
    assert s._report_status_by_reception is None
    s.report_status_for_reception("P1")
    n = len(s.scans)
    s.report_status_for_reception("P1")
    assert len(s.scans) > n, "kill switch must restore the per-call scan"


def test_memo_is_armed_by_the_stream_and_dropped_on_clear():
    src = _widget_src()
    assert "self._begin_report_status_memo()" in _method(src, "load_progressive")
    assert "self._end_report_status_memo()" in _method(src, "_on_stream_settled")
    assert "self._end_report_status_memo()" in _method(src, "clear_table")
    assert "self._end_report_status_memo()" in _method(src, "_clear_table_legacy")
    # and the insert path feeds it
    assert "_rs_memo.setdefault(str(patient_id).strip(), report_status)" in src


def test_assign_icon_resolves_report_status_once():
    """It used to call the full-table scan TWICE per rendered row."""
    fn = _method(_widget_src(), "_assign_icon_state")
    assert fn.count("self.report_status_for_reception(reception_id)") == 1
    assert "report_status=_report_status" in fn


# ── 6. Sort's checkbox-restore reads one field, not thirty ──────────────────

def test_row_study_uid_matches_extract_row_data():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import COL
    P = _P()
    QApplication.instance() or QApplication([])

    class _S:
        _row_study_uid = P._row_study_uid
        _extract_row_data = P._extract_row_data

        def __init__(self, table):
            self.results_table = table

    t = QTableWidget(3, max(COL.values()) + 1)
    for r in range(3):
        for c in range(t.columnCount()):
            t.setItem(r, c, QTableWidgetItem(""))
    # row 0: visible uid text
    t.item(0, COL['study_uid']).setText("1.2.VISIBLE")
    # row 1: no text, uid only in the UserRole+10 list
    t.item(1, COL['study_uid']).setData(Qt.UserRole + 10, ["1.2.STORED", "1.2.OTHER"])
    # row 2: nothing at all

    s = _S(t)
    for row in range(3):
        rd = s._extract_row_data(row)
        expected = rd.get('study_uid') if rd else None
        assert s._row_study_uid(row) == expected, f"row {row} diverged"
    assert s._row_study_uid(0) == "1.2.VISIBLE"
    assert s._row_study_uid(1) == "1.2.STORED"
    assert s._row_study_uid(2) is None


def test_programmatic_sort_no_longer_builds_a_dict_per_row():
    fn = _method(_widget_src(), "_programmatic_sort")
    assert "self._extract_row_data(" not in fn
    assert fn.count("self._row_study_uid(row)") == 2   # capture pass + restore pass


# ── 7. INO stores: mtime-guarded read caches ────────────────────────────────

def test_server_state_store_is_read_once_until_the_file_changes(tmp_path, monkeypatch):
    from modules.network import ino_assignment_server_state as st
    monkeypatch.setattr(st, "_base_dir", lambda: str(tmp_path))
    st._invalidate_cache()

    (tmp_path / "server_state.json").write_text(
        json.dumps({"R1": {"assigned": True, "assignee_name": "AAA"}}), encoding="utf-8")

    opened = []
    real_open = open

    def _spy(*a, **k):
        opened.append(str(a[0]))
        return real_open(*a, **k)

    monkeypatch.setattr("builtins.open", _spy)
    assert st.get_state("R1")["assignee_name"] == "AAA"
    first = len(opened)
    for _ in range(20):
        st.get_state("R1")
    assert len(opened) == first, "repeat reads must be served from the cache"

    # a CHANGED file must be picked up (different size => different key)
    monkeypatch.setattr("builtins.open", real_open)
    (tmp_path / "server_state.json").write_text(
        json.dumps({"R1": {"assigned": True, "assignee_name": "BBBBBBBB"}}), encoding="utf-8")
    assert st.get_state("R1")["assignee_name"] == "BBBBBBBB"


def test_server_state_returns_a_copy_so_callers_cannot_poison_the_cache(tmp_path, monkeypatch):
    from modules.network import ino_assignment_server_state as st
    monkeypatch.setattr(st, "_base_dir", lambda: str(tmp_path))
    st._invalidate_cache()
    (tmp_path / "server_state.json").write_text(
        json.dumps({"R1": {"assignee_name": "AAA"}}), encoding="utf-8")

    got = st.get_state("R1")
    got["assignee_name"] = "MUTATED"
    assert st.get_state("R1")["assignee_name"] == "AAA"


def test_server_state_cache_kill_switch(tmp_path, monkeypatch):
    from modules.network import ino_assignment_server_state as st
    monkeypatch.setenv("AIPACS_INO_STORE_CACHE", "0")
    monkeypatch.setattr(st, "_base_dir", lambda: str(tmp_path))
    st._invalidate_cache()
    (tmp_path / "server_state.json").write_text(json.dumps({"R1": {"a": 1}}), encoding="utf-8")

    opened = []
    real_open = open
    monkeypatch.setattr("builtins.open",
                        lambda *a, **k: (opened.append(str(a[0])), real_open(*a, **k))[1])
    st.get_state("R1")
    st.get_state("R1")
    assert len(opened) >= 2, "kill switch must restore read-every-time"


def test_history_store_is_read_once_until_it_changes(tmp_path, monkeypatch):
    from modules.network import ino_assignment_history as h
    monkeypatch.setattr(h, "_base_dir", lambda: str(tmp_path))
    h._invalidate_cache()

    p = tmp_path / "history.jsonl"
    p.write_text(json.dumps({"reception_id": "R1", "action": "assign"}) + "\n",
                 encoding="utf-8")

    opened = []
    real_open = open
    monkeypatch.setattr("builtins.open",
                        lambda *a, **k: (opened.append(str(a[0])), real_open(*a, **k))[1])

    assert len(h.read_for_reception("R1")) == 1
    first = len(opened)
    for _ in range(20):
        h.read_for_reception("R1")
    assert len(opened) == first, "repeat reads must be served from the cache"

    monkeypatch.setattr("builtins.open", real_open)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"reception_id": "R1", "action": "complete"}) + "\n")
    assert len(h.read_for_reception("R1")) == 2, "an appended entry must be seen"


def test_history_rows_are_copies(tmp_path, monkeypatch):
    from modules.network import ino_assignment_history as h
    monkeypatch.setattr(h, "_base_dir", lambda: str(tmp_path))
    h._invalidate_cache()
    (tmp_path / "history.jsonl").write_text(
        json.dumps({"reception_id": "R1", "action": "assign"}) + "\n", encoding="utf-8")

    rows = h.read_all()
    rows[0]["action"] = "MUTATED"
    assert h.read_all()[0]["action"] == "assign"


def test_ino_config_cache_still_sees_an_edited_config(tmp_path, monkeypatch):
    from modules.network import ino_assignment as ia
    import PacsClient.utils.config as cfg
    monkeypatch.setattr(cfg, "SOCKET_CONFIG_PATH", str(tmp_path), raising=False)
    ia._CFG_CACHE_KEY = None

    path = tmp_path / ia._CONFIG_FILENAME
    path.write_text(json.dumps({"enabled": True, "note": "aaaa"}), encoding="utf-8")
    assert ia._config().get("enabled") is True
    path.write_text(json.dumps({"enabled": False, "note": "bb"}), encoding="utf-8")
    assert ia._config().get("enabled") is False


# ── 8. Per-row disk work moved off the GUI thread ───────────────────────────

def test_resolve_display_paths_stamps_a_renderable_verdict(monkeypatch):
    from PacsClient.pacs.workstation_ui.home_ui import home_search_service as hss

    seen = []

    def _fake(patient):
        seen.append(patient.get('study_uid'))
        return "C:/store/ok" if patient.get('study_uid') == 'ok' else None

    monkeypatch.setattr(hss, "_resolve_renderable_study_path", _fake)
    rows = [{'study_uid': 'ok'}, {'study_uid': 'missing'}]
    hss.HomeSearchService._resolve_display_paths(rows)

    assert rows[0]['_aipacs_renderable'] is True
    assert rows[0]['study_path'] == "C:/store/ok"
    assert rows[1]['_aipacs_renderable'] is False
    assert seen == ['ok', 'missing']


def test_resolve_display_paths_never_raises(monkeypatch):
    from PacsClient.pacs.workstation_ui.home_ui import home_search_service as hss

    def _boom(patient):
        raise OSError("store offline")

    monkeypatch.setattr(hss, "_resolve_renderable_study_path", _boom)
    rows = [{'study_uid': 'x'}]
    hss.HomeSearchService._resolve_display_paths(rows)
    assert rows[0]['_aipacs_renderable'] is False


def test_render_one_uses_the_precomputed_verdict_with_an_inline_fallback():
    """A row the worker has not reached yet must still resolve — the off-thread
    pass is an optimisation, never a precondition."""
    src = _search_src()
    fn = _method(src, "search_local")
    assert "if '_aipacs_renderable' in patient:" in fn
    assert "elif _resolve_renderable_study_path(patient) is None:" in fn
    # the head/tail split keeps first paint fast
    assert "patients_display[:_PATHS_HEAD]" in fn
    assert "patients_display[_PATHS_HEAD:]" in fn
    # and the disk logic exists in exactly ONE place now
    assert fn.count("has_subfolders") == 0, "render_one must not re-implement it"


def test_search_local_primes_both_caches_before_rendering():
    fn = _method(_search_src(), "search_local")
    assert "self._collect_list_prefetch" in fn
    assert "prime_imported_on_cache" in fn
    assert "prime_visited_patient_ids" in fn


# ── 9. Every OPT-50 switch defaults ON ──────────────────────────────────────

@pytest.mark.parametrize("env,fn_name,src_kind", [
    ("AIPACS_LIST_UID_INDEX", "_uid_index_enabled", "widget"),
    ("AIPACS_LIST_DB_PREFETCH", "_db_prefetch_enabled", "widget"),
    ("AIPACS_LIST_BATCH_FINALIZE", "_batch_finalize_enabled", "widget"),
    ("AIPACS_LIST_REPORT_MEMO", "_report_memo_enabled", "widget"),
])
def test_widget_flags_default_on(env, fn_name, src_kind, monkeypatch):
    monkeypatch.delenv(env, raising=False)
    P = _P()
    assert getattr(P, fn_name)() is True
    monkeypatch.setenv(env, "0")
    assert getattr(P, fn_name)() is False


def test_search_service_flags_default_on(monkeypatch):
    from PacsClient.pacs.workstation_ui.home_ui import home_search_service as hss
    for env, fn in (("AIPACS_LIST_PATHS_OFFTHREAD", hss._paths_offthread_enabled),
                    ("AIPACS_LIST_DB_PREFETCH", hss._db_prefetch_enabled)):
        monkeypatch.delenv(env, raising=False)
        assert fn() is True
        monkeypatch.setenv(env, "0")
        assert fn() is False
        monkeypatch.delenv(env, raising=False)


def test_ino_store_cache_flag_defaults_on(monkeypatch):
    from modules.network import ino_assignment_server_state as st
    from modules.network import ino_assignment_history as h
    monkeypatch.delenv("AIPACS_INO_STORE_CACHE", raising=False)
    assert st._store_cache_enabled() is True
    assert h._store_cache_enabled() is True
    monkeypatch.setenv("AIPACS_INO_STORE_CACHE", "0")
    assert st._store_cache_enabled() is False
    assert h._store_cache_enabled() is False
