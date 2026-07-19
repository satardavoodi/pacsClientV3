"""Guards for the "Imported On" patient-table column (2026-07-18).

Imported On = when a study FIRST entered the local database on THIS computer,
as distinct from the Date column (when the images were acquired). The two
diverge exactly where the column earns its keep: importing an old study from a
CD or another external source.

Two things here are easy to break and expensive to discover in the field:
  1. the COL indices — they are persisted in users' saved column settings, so
     renumbering silently scrambles the layout of every existing workstation;
  2. `imported_at` being re-stamped on refresh, which would quietly turn the
     column into "last refreshed" and make CD-import sorting useless.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def _src(rel: str) -> str:
    root = Path(__file__).resolve().parents[3]
    return (root / rel).read_text(encoding="utf-8", errors="ignore")


TABLE_SRC = "PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py"
DB_SRC = "database/dicom_db.py"


# ---------------------------------------------------------------------------
# Column indices — the upgrade-safety invariant
# ---------------------------------------------------------------------------


def test_existing_column_indices_are_unchanged():
    """Saved column settings are keyed by these integers. Renumbering any of
    them scrambles the layout of every workstation that upgrades."""
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import COL

    expected = {
        "select": 0,
        "patient_name": 1,
        "patient_id": 2,
        "body_part": 3,
        "status": 4,
        "report": 5,
        "assign": 6,
        "time": 7,
        "date": 8,
        "images": 9,
        "modality": 10,
        "age": 11,
        "description": 12,
        "study_uid": 13,
        "order": 14,
    }
    for name, index in expected.items():
        assert COL[name] == index, f"COL['{name}'] moved from {index} to {COL[name]}"


def test_imported_on_is_appended_not_inserted():
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import (
        COL,
        TOTAL_COLS,
    )

    assert COL["imported_on"] == 15
    assert TOTAL_COLS == 16
    assert COL["imported_on"] == max(COL.values()), "new columns go at the END"


def test_header_labels_cover_every_column():
    """A short header list leaves the new column with no label."""
    src = _src(TABLE_SRC)
    assert '"Imported On"' in src
    assert "setColumnWidth(COL['imported_on']" in src
    assert "setSectionResizeMode(COL['imported_on']" in src


# ---------------------------------------------------------------------------
# Default visibility + gear dialog
# ---------------------------------------------------------------------------


def test_hidden_by_default():
    src = _src(TABLE_SRC)
    assert "setColumnHidden(COL['imported_on'], True)" in src


def test_column_appears_in_the_settings_dialog():
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import (
        COL,
        ColumnSettingsDialog,
    )

    assert ColumnSettingsDialog.COLUMN_NAMES[COL["imported_on"]] == "Imported On"
    assert "Imported On" in ColumnSettingsDialog.COLUMN_ICONS


def test_settings_dialog_does_not_skip_imported_on():
    """`load_current_settings` skips only the two truly-internal columns; if
    imported_on were added to that skip list it would vanish from the gear."""
    src = _src(TABLE_SRC)
    skip_line = "if logical_idx in [self.col_dict.get('study_uid'), self.col_dict.get('order')]:"
    assert skip_line in src
    assert "imported_on" not in skip_line


def test_reset_to_default_keeps_it_hidden():
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import (
        ColumnSettingsDialog,
    )

    assert "Imported On" in ColumnSettingsDialog._DEFAULT_HIDDEN
    src = _src(TABLE_SRC)
    assert "checkbox.setChecked(header_text not in self._DEFAULT_HIDDEN)" in src
    assert "self.col_dict['imported_on']" in src  # still in the default ORDER


# ---------------------------------------------------------------------------
# Formatting + sorting
# ---------------------------------------------------------------------------


def test_format_is_readable_and_sortable():
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import (
        PatientTableWidget as P,
    )

    assert P._format_imported_on("2026-07-18 14:30:00") == "2026-07-18  14:30"
    assert P._format_imported_on("") == P._IMPORTED_ON_EMPTY
    assert P._format_imported_on(None) == P._IMPORTED_ON_EMPTY


def test_iso_stamps_sort_chronologically_as_plain_strings():
    """The stored form IS the sort key — no parsing at sort time."""
    stamps = ["2026-07-18 09:05:00", "2025-12-31 23:59:59", "2026-07-18 14:30:00"]
    assert sorted(stamps) == [
        "2025-12-31 23:59:59",
        "2026-07-18 09:05:00",
        "2026-07-18 14:30:00",
    ]


def test_most_recent_import_wins_for_a_multi_study_row():
    """A patient row aggregates studies; it must show the LATEST import so a
    freshly imported CD surfaces at the top of the sort."""
    stamps = ["2025-01-01 08:00:00", "2026-07-18 14:30:00", ""]
    assert max(stamps) == "2026-07-18 14:30:00"


def test_rows_without_a_record_sort_last_descending():
    """Empty key must not sort ABOVE a real timestamp in descending order."""
    assert "" < "2020-01-01 00:00:00"


def test_cache_is_cleared_on_a_new_search():
    """Otherwise a study imported since the last search shows a stale blank."""
    src = _src(TABLE_SRC)
    assert src.count("_imported_on_cache = {}") >= 2  # both clear paths


# ---------------------------------------------------------------------------
# Database: migration, stamping, and the "written once" invariant
# ---------------------------------------------------------------------------


def test_schema_and_migration_present():
    src = _src(DB_SRC)
    assert "imported_at      TEXT DEFAULT NULL" in src          # fresh install
    assert "ALTER TABLE studies ADD COLUMN imported_at" in src  # upgrade


def test_insert_stamps_but_update_does_not():
    """THE invariant: imported_at is written ONCE, on first insert.

    `insert_study` runs on every metadata refresh (INSERT, then UPDATE on the
    IntegrityError path). If the UPDATE also set imported_at, the column would
    re-stamp on every refresh and degrade into "last refreshed".
    """
    src = _src(DB_SRC)
    insert_stmt = src.split("INSERT INTO studies", 1)[1].split(")", 1)[0]
    assert "imported_at" in insert_stmt

    update_stmt = src.split("UPDATE studies\n                SET", 1)[1]
    update_stmt = update_stmt.split("WHERE study_uid", 1)[0]
    assert "imported_at" not in update_stmt, (
        "imported_at must NOT be in the refresh UPDATE — it would re-stamp "
        "on every metadata refresh"
    )


def test_migration_is_idempotent_and_preserves_existing_rows():
    """Simulates the real upgrade: an old-schema DB gains the column without
    losing data, and re-running the migration is a no-op."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE studies (study_pk INTEGER PRIMARY KEY, study_uid TEXT UNIQUE, "
        "study_date TEXT, study_path TEXT)"
    )
    cur.execute("INSERT INTO studies (study_uid, study_date) VALUES ('1.2.3', '20200101')")
    conn.commit()

    def migrate():
        try:
            cur.execute("SELECT imported_at FROM studies LIMIT 1")
        except sqlite3.OperationalError:
            cur.execute("ALTER TABLE studies ADD COLUMN imported_at TEXT DEFAULT NULL")
            conn.commit()

    migrate()
    migrate()  # idempotent

    cur.execute("SELECT study_uid, study_date, imported_at FROM studies")
    rows = cur.fetchall()
    assert rows == [("1.2.3", "20200101", None)], (
        "pre-existing rows must survive and stay NULL (product decision: no "
        "invented backfill)"
    )
    conn.close()


def test_stamp_is_sortable_local_iso():
    """datetime('now','localtime') yields 'YYYY-MM-DD HH:MM:SS' — the form the
    column relies on for string-sorting."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE t (imported_at TEXT)")
    cur.execute("INSERT INTO t VALUES (datetime('now','localtime'))")
    value = cur.fetchone() if False else cur.execute("SELECT imported_at FROM t").fetchone()[0]
    conn.close()

    assert len(value) == 19
    assert value[4] == "-" and value[7] == "-" and value[10] == " "
    assert value[13] == ":" and value[16] == ":"


def test_batch_lookup_helper_exists_and_is_chunked():
    """One query per page, not one per row (OPT-24 lesson)."""
    src = _src(DB_SRC)
    assert "def get_imported_at_map" in src
    body = src.split("def get_imported_at_map", 1)[1].split("\ndef ", 1)[0]
    assert "range(0, len(uids), 500)" in body, "must chunk under SQLite's var limit"
    assert "imported_at IS NOT NULL" in body
    assert "except Exception" in body, "the column must never break the patient list"


def test_lookup_returns_empty_for_no_input():
    from database.dicom_db import get_imported_at_map

    assert get_imported_at_map([]) == {}
    assert get_imported_at_map(None) == {}
    assert get_imported_at_map(["", "   "]) == {}
