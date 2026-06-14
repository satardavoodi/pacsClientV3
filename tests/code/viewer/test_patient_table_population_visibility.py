"""Regression guard: the home patient table must actually RENDER rows after the
server-search bulk-insert population path.

Why this exists (2026-06-14 impatient-user stress test)
=======================================================
A live-driving session hit a P0: a server patient search succeeded
(`socket_patient_service … Found 38 patients`) and rows were added to the
patient table without error, yet the home page showed an EMPTY table (no header,
no rows) — the table widget was hidden / zero-sized in its embedded pane, so the
added rows were never visible. No existing test exercised "search results are
actually shown", so nothing caught it.

This guard exercises the exact sequence `HomeSearchService.search_server()` uses
to fill the table — `clear_table()` → `begin_bulk_insert()` → N×
`add_patient_data(...)` → `end_bulk_insert()` — and asserts the rows are present
AND visibly rendered (non-zero row heights, header visible). It runs fully
offscreen and does not need the network, the home panel, or a live app.

See docs/reports/IMPATIENT_USER_STRESS_TEST_2026-06-14.md (§6 P0).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AIPACS_NO_TAKEOVER", "1")


@pytest.fixture(scope="module")
def _qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _make_table(_qapp):
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import PatientTableWidget
    w = PatientTableWidget()
    w.resize(1300, 800)
    w.show()
    _qapp.processEvents()
    return w


def _add_rows(w, n):
    """Add ``n`` synthetic patient rows the way the socket-search path does."""
    for i in range(n):
        w.add_patient_data(
            patient_id="STRESS%d" % i,
            patient_name="Patient %d" % i,
            study_date="20260614",
            study_time="120000",
            body_part="CHEST",
            age="40",
            description="desc %d" % i,
            modality="CT",
            study_uid="1.2.840.stress.%d" % i,
            study_uids=["1.2.840.stress.%d" % i],
            series_count=5,
            images_count=100,
            report_status="pending",
            reporting_physician="",
            initial_comment="",
        )


def test_added_rows_are_present_and_rendered(_qapp):
    """After add_patient_data, rows exist AND are visibly rendered (the P0 contract)."""
    w = _make_table(_qapp)
    rt = w.results_table
    assert rt.isVisible(), "results_table must be visible when the widget is shown"
    assert rt.horizontalHeader().isVisible(), "the column header must be visible"

    _add_rows(w, 3)
    _qapp.processEvents()

    assert rt.rowCount() == 3, f"expected 3 rows, got {rt.rowCount()}"
    # Rows must occupy real space — a zero-height table is the P0 failure mode
    # (rows added but nothing shown).
    assert rt.height() > 0
    assert all(rt.rowHeight(r) > 0 for r in range(rt.rowCount())), (
        "added rows must have non-zero height (they were invisible in the P0)"
    )


def test_bulk_insert_population_path_renders(_qapp):
    """The exact search_server() sequence (clear → begin_bulk → add×N → end_bulk)
    must leave the table populated and visible — not blanked by the bulk wrapper."""
    w = _make_table(_qapp)
    rt = w.results_table

    w.clear_table()
    _qapp.processEvents()
    assert rt.rowCount() == 0

    w.begin_bulk_insert()
    _add_rows(w, 5)
    w.end_bulk_insert()
    _qapp.processEvents()

    assert rt.rowCount() == 5, f"bulk-insert path must add all rows, got {rt.rowCount()}"
    # end_bulk_insert() must re-enable painting — a stuck setUpdatesEnabled(False)
    # would leave a populated-but-blank table.
    assert rt.updatesEnabled(), "end_bulk_insert must restore updatesEnabled(True)"
    assert rt.isVisible()


def test_clear_table_empties(_qapp):
    """clear_table() removes all rows (no stale rows linger)."""
    w = _make_table(_qapp)
    _add_rows(w, 4)
    _qapp.processEvents()
    assert w.results_table.rowCount() == 4
    w.clear_table()
    _qapp.processEvents()
    assert w.results_table.rowCount() == 0
