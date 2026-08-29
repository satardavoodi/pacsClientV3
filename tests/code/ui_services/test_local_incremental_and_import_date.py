"""Local-list incremental loading + Advanced-Search import-date filter (2026-07-24).

Two features:
  1. The Local patient list streams in — a small FIRST batch immediately, the rest
     in the background (idle timer) + on scroll — so a very large local DB never
     freezes the page.
  2. Advanced Patient Search gains an IMPORT-DATE filter (Imported Today /
     Yesterday / Two Days Ago / Custom Date / Date Range) that queries
     studies.imported_at (when the study entered THIS local DB), NOT study_date.
"""
import os
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ── 1. DB: import-date filter on studies.imported_at ────────────────────────

def _isolate_db(tmp_path, monkeypatch):
    """Redirect the DB to a temp file (per the DB test-isolation rule: patch
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


def _seed(conn):
    cur = conn.cursor()
    cur.execute("INSERT INTO patients (patient_id, patient_name) VALUES ('P1','ALICE')")
    pk = cur.execute("SELECT patient_pk FROM patients WHERE patient_id='P1'").fetchone()[0]
    rows = [
        ("u_today",  "20200101", "2026-07-24 09:00:00"),
        ("u_yest",   "20200101", "2026-07-23 18:30:00"),
        ("u_2days",  "20200101", "2026-07-22 08:00:00"),
        ("u_old",    "20200101", "2026-01-01 08:00:00"),
        ("u_null",   "20200101", None),   # never stamped (pre-existing row)
    ]
    for uid, sdate, imp in rows:
        cur.execute(
            "INSERT INTO studies (study_uid, patient_fk, study_date, imported_at) "
            "VALUES (?,?,?,?)", (uid, pk, sdate, imp),
        )
    conn.commit()


def test_import_date_filter_single_day(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from database import dicom_db
    dicom_db.init_database()
    with dicom_db.get_db_connection() as conn:
        _seed(conn)

    r = dicom_db.search_patients_local(
        {"import_date_from": "2026-07-24", "import_date_to": "2026-07-24"}
    )
    assert {x["study_uid"] for x in r} == {"u_today"}


def test_import_date_filter_range(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from database import dicom_db
    dicom_db.init_database()
    with dicom_db.get_db_connection() as conn:
        _seed(conn)

    r = dicom_db.search_patients_local(
        {"import_date_from": "2026-07-22", "import_date_to": "2026-07-23"}
    )
    assert {x["study_uid"] for x in r} == {"u_yest", "u_2days"}


def test_import_date_filter_normalizes_reversed_range(tmp_path, monkeypatch):
    """A reversed custom range must not silently produce an empty result set."""
    _isolate_db(tmp_path, monkeypatch)
    from database import dicom_db
    dicom_db.init_database()
    with dicom_db.get_db_connection() as conn:
        _seed(conn)

    r = dicom_db.search_patients_local(
        {"import_date_from": "2026-07-24", "import_date_to": "2026-07-22"}
    )
    assert {x["study_uid"] for x in r} == {"u_today", "u_yest", "u_2days"}


def test_import_date_filter_uses_imported_at_not_study_date(tmp_path, monkeypatch):
    """All rows share study_date 20200101; the filter must key on imported_at."""
    _isolate_db(tmp_path, monkeypatch)
    from database import dicom_db
    dicom_db.init_database()
    with dicom_db.get_db_connection() as conn:
        _seed(conn)

    # a study-date range that would match ALL rows must NOT leak through the
    # import-date filter
    r = dicom_db.search_patients_local(
        {"import_date_from": "2026-07-24", "import_date_to": "2026-07-24",
         "date_from": "20200101", "date_to": "20200101"}
    )
    assert {x["study_uid"] for x in r} == {"u_today"}
    # NULL imported_at rows never match an import-date filter
    assert "u_null" not in {x["study_uid"] for x in r}


def test_no_import_filter_returns_all(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from database import dicom_db
    dicom_db.init_database()
    with dicom_db.get_db_connection() as conn:
        _seed(conn)
    r = dicom_db.search_patients_local({})
    assert {"u_today", "u_yest", "u_2days", "u_old", "u_null"} <= {x["study_uid"] for x in r}


# ── 2. Advanced dialog: import-date query building ──────────────────────────

def _dialog():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from PacsClient.pacs.workstation_ui.home_ui.advanced_search_dialog import AdvancedSearchDialog
    return AdvancedSearchDialog()


def _set_import_preset(d, data):
    for i in range(d.import_preset.count()):
        if d.import_preset.itemData(i) == data:
            d.import_preset.setCurrentIndex(i)
            return
    raise AssertionError(f"import preset {data!r} not found")


def test_dialog_default_has_no_import_date():
    d = _dialog()
    q = d.get_query()
    assert q["import_date_from"] is None and q["import_date_to"] is None


def test_dialog_imported_today_yesterday_twodays():
    from PySide6.QtCore import QDate
    d = _dialog()
    today = QDate.currentDate()

    _set_import_preset(d, 0)
    q = d.get_query()
    assert q["import_date_from"] == today.toString("yyyy-MM-dd")
    assert q["import_date_to"] == today.toString("yyyy-MM-dd")

    _set_import_preset(d, 1)
    q = d.get_query()
    y = today.addDays(-1).toString("yyyy-MM-dd")
    assert q["import_date_from"] == y and q["import_date_to"] == y

    _set_import_preset(d, 2)
    q = d.get_query()
    t = today.addDays(-2).toString("yyyy-MM-dd")
    assert q["import_date_from"] == t and q["import_date_to"] == t


def test_dialog_custom_single_and_range():
    from PySide6.QtCore import QDate
    d = _dialog()

    _set_import_preset(d, "single")
    d.import_from.setDate(QDate(2026, 7, 5))
    q = d.get_query()
    assert q["import_date_from"] == "2026-07-05" and q["import_date_to"] == "2026-07-05"

    _set_import_preset(d, "range")
    d.import_from.setDate(QDate(2026, 7, 1))
    d.import_to.setDate(QDate(2026, 7, 10))
    q = d.get_query()
    assert q["import_date_from"] == "2026-07-01" and q["import_date_to"] == "2026-07-10"


def test_dialog_normalizes_reversed_import_range():
    from PySide6.QtCore import QDate
    d = _dialog()

    _set_import_preset(d, "range")
    d.import_from.setDate(QDate(2026, 7, 10))
    d.import_to.setDate(QDate(2026, 7, 1))
    q = d.get_query()
    assert q["import_date_from"] == "2026-07-01"
    assert q["import_date_to"] == "2026-07-10"


def test_dispatch_routes_import_date_to_local_search():
    """The advanced dispatch must route an import-date query to the LOCAL DB
    search (import date is local-only), not the PACS server."""
    import inspect
    from PacsClient.pacs.workstation_ui.home_ui.home_panel import _hp_search
    src = inspect.getsource(_hp_search._HPSearchMixin._on_advanced_search_requested) \
        if hasattr(_hp_search, "_HPSearchMixin") else inspect.getsource(
            _hp_search.__dict__["_on_advanced_search_requested"]
        ) if "_on_advanced_search_requested" in _hp_search.__dict__ else None
    if src is None:
        # fall back to file text
        import pathlib
        src = pathlib.Path(_hp_search.__file__).read_text(encoding="utf-8")
    assert "import_date_from" in src
    assert "search_local(extra_criteria=extra)" in src
    assert "search_server_advanced(query)" in src  # server path preserved


# ── 3. Incremental Local-list loading (progressive) ─────────────────────────

def _progressive_stub(bg_delay_ms=0):
    from unittest.mock import MagicMock
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import PatientTableWidget as P

    class _Stub:
        _PROGRESSIVE_BATCH = P._PROGRESSIVE_BATCH
        _PROGRESSIVE_INITIAL_BATCH = P._PROGRESSIVE_INITIAL_BATCH
        _PROGRESSIVE_BG_BATCH = P._PROGRESSIVE_BG_BATCH
        _PROGRESSIVE_BG_DELAY_MS = bg_delay_ms
        load_progressive = P.load_progressive
        _progressive_render_next = P._progressive_render_next
        _schedule_progressive_background = P._schedule_progressive_background
        _progressive_background_step = P._progressive_background_step
        _progressive_bg_enabled = staticmethod(P._progressive_bg_enabled)
        _on_progressive_scroll = P._on_progressive_scroll
        # OPT-50 (2026-08-03): load_progressive now arms the render-pass
        # report-status memo, so the double has to provide that collaborator.
        # Borrowed from the real class rather than stubbed out, so the double
        # cannot silently drift from it.
        _report_memo_enabled = staticmethod(P._report_memo_enabled)
        _begin_report_status_memo = P._begin_report_status_memo

        def __init__(self):
            self.results_table = MagicMock()
            self.rendered = []

        def begin_bulk_insert(self):
            pass

        def end_bulk_insert(self):
            pass

        def _update_progressive_count_label(self):
            pass

    return _Stub()


def test_first_paint_is_small_batch_then_background_fills(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    s = _progressive_stub(bg_delay_ms=1)
    items = list(range(250))
    render_one = lambda it: s.rendered.append(it)

    s.load_progressive(items, render_one)
    # first paint = exactly the small initial batch (the "first 20")
    assert len(s.rendered) == s._PROGRESSIVE_INITIAL_BATCH == 20
    assert s.rendered == list(range(20))

    # background streams the rest in without any scroll — spin the loop
    import time
    deadline = time.time() + 8
    while len(s.rendered) < len(items) and time.time() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert len(s.rendered) == len(items), "background streaming must load every row"
    assert s.rendered == items  # order preserved, no gaps/dupes


def test_background_disabled_renders_only_first_batch(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("AIPACS_PROGRESSIVE_LOCAL_BG", "0")

    s = _progressive_stub()
    items = list(range(100))
    s.load_progressive(items, lambda it: s.rendered.append(it))
    app.processEvents()
    # with background off, only the first batch renders up front (rest on scroll)
    assert len(s.rendered) == 20
    # a manual advance (simulating scroll) renders the next batch
    s._progressive_render_next(s._PROGRESSIVE_BG_BATCH)
    assert len(s.rendered) == 60


def test_new_load_invalidates_prior_background(monkeypatch):
    """Starting a new progressive load must not let an old background timer keep
    appending stale rows (generation guard)."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    s = _progressive_stub(bg_delay_ms=5)
    s.load_progressive(list(range(200)), lambda it: s.rendered.append(it))
    gen1 = s._prog_bg_gen
    s.load_progressive(list(range(5)), lambda it: s.rendered.append(it))  # new load
    assert s._prog_bg_gen == gen1 + 1
    # the stale-gen background step is a no-op
    before = len(s.rendered)
    s._progressive_background_step(gen1)
    assert len(s.rendered) == before
